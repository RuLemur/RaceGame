import math

import pygame
import pymunk

from car_racer.cars.abs_car import Car
from car_racer.constants import GRAY, WHITE, SENSOR_RANGE, TICK_RATE, PX_PER_METER
from car_racer.screen.screen import Screen
from helpers.calculate import calculate_end_pos, get_midpoint, cast_ray, min_distance_to_segments

CAR_HEIGHT = 80
CAR_WIDTH = 50
VELOCITY_EPSILON = 0.1
ROTATE_POWER = 3.0  # жёсткий потолок угловой скорости, rad/s (страховка, реально почти не достигается)
THROTTLE_POWER = 200  # Сила тяги
MAX_SPEED = 400  # px/s
BRAKE_RATE = 15

# --- Руль: угол передних колёс вместо прямой угловой скорости --------------
# Раньше turn() задавал ЦЕЛЕВУЮ угловую скорость напрямую, плюс ручная
# поправка SPEED_EFFECT на скорость. Теперь руль - это угол δ передних колёс,
# а угловая скорость выводится из скорости и δ по кинематике велосипеда:
#     ω = v / WHEELBASE * tan(δ)
# Отсюда САМО следует то, что раньше имитировалось вручную: машина не
# вращается на месте (ω → 0 при v → 0), а боковое ускорение a = v·ω
# ограничивается сцеплением (см. GRIP_ACCEL ниже) - поэтому на высокой
# скорости руль естественно "слабее".
MAX_STEERING_ANGLE = 0.6   # макс. угол передних колёс, rad (~34°) - задаёт мин. радиус поворота
STEERING_RATE = 6.0        # конечная скорость поворота руля, rad/s - turn() не может "дёрнуть" мгновенно
WHEELBASE = 30.0           # база между осями, px (~1.5 м при PX_PER_METER=20)

# --- Модель сцепления (круг трения) ----------------------------------------
# Доступное сцепление шин ограничивает СУММУ продольного (разгон/торможение)
# и поперечного (поворот) ускорения: жать газ в пол и резко поворачивать
# одновременно физически нельзя.
#
# Раньше GRIP_ACCEL=2000 px/s^2 было УСЛОВНОЙ этикеткой (~10g при
# PX_PER_METER=20), подобранной под старую лаг-модель разгона, а не под
# физику. Теперь это честная калибровка через PX_PER_METER:
# GRIP_ACCEL_PER_G = 1g в px/s^2 (g=9.81 м/с^2, 1 м = PX_PER_METER px),
# GRIP_ACCEL = 1.5g - правдоподобный предел сцепления картинга на асфальте.
# Побочный эффект (осознанный): теперь круг трения ограничивает и разгон по
# прямой (~1.5g "пробуксовки" при старте), и торможение - раньше он их почти
# не трогал, отдавая весь бюджет продольному ускорению.
GRIP_ACCEL_PER_G = 9.81 * PX_PER_METER
GRIP_ACCEL = 1.5 * GRIP_ACCEL_PER_G

# --- Снос (slip): вектор скорости не успевает за курсом --------------------
# Раньше velocity каждый тик жёстко проецировалась на курс (self.body.angle) -
# машина ехала "по рельсам", бокового скольжения не существовало в принципе,
# а снос/занос/скраб имитировались ручными "киками" (UNDERSTEER_*/OVERSTEER_*/
# STEER_SCRUB_COEFF/NO_DIFF_*) по |Δ газа/руля| между тиками - эти эффекты
# удалены как заплатки. Теперь направление вектора скорости
# (self.velocity_heading) догоняет курс (self.body.angle) с конечной
# скоростью - на высокой скорости или при резком руле машина заметно "плывёт"
# носом внутрь поворота (угол скольжения), как настоящий картинг, а не
# мгновенно следует за курсом.
# SLIP_ALIGN_GAIN - базовая скорость "прилипания" направления скорости к
# курсу (1/с); SLIP_SPEED_FACTOR - насколько она падает с ростом скорости
# (инерция: на высокой скорости машина дольше сохраняет прежнее направление).
SLIP_ALIGN_GAIN = 7.0
SLIP_SPEED_FACTOR = 0.012

# --- Мощность и масса --------------------------------------------------
# Разгон под тягой физически зависит от мощности двигателя и массы (F=ma,
# при этом мощность P~F*v - тяжелее машина/слабее мотор -> медленнее разгон).
# А вот торможение и сцепление в повороте (GRIP_ACCEL выше) НЕ зависят от
# массы: максимальное тормозное/поперечное ускорение a=μg определяется только
# трением шин о асфальт и НЕ зависит от того, тяжёлая машина или лёгкая (сила
# трения и масса сокращаются) - поэтому масса ниже влияет только на разгон.
#
# ENGINE_POWER_HP/CAR_MASS выражены в узнаваемых единицах (л.с., кг) для
# наглядности в UI-настройках, но, как и REFERENCE_MASS_KG/REFERENCE_POWER_HP
# ниже, это не независимая физическая калибровка (в проекте её нет и для
# длины/времени) - дефолты подобраны так, чтобы РЕФЕРЕНСНЫЕ значения давали
# двигательный потолок ускорения (см. _desired_speed), РОВНО равный
# GRIP_ACCEL - т.е. на референсных мощности/массе машина уже упирается в
# сцепление шин, а не в мотор; ниже референса ограничивает мотор, выше -
# всё равно сцепление (мощность мотора не может "перебить" сцепление шин).
ENGINE_POWER_HP = 15.0      # типичный прокатный картинг (5-40 л.с. - разумный диапазон)
REFERENCE_POWER_HP = 15.0

CAR_MASS = 1.0              # масса в "игровых" единицах pymunk (для body/moment)
REFERENCE_MASS = 1.0
REFERENCE_MASS_KG = 160.0   # ~ картинг + пилот, для отображения CAR_MASS в кг в UI

# "Утешительный приз" за пройденную дистанцию (см. add_distance_consolation_fitness)
# - небольшая, но НЕНУЛЕВАЯ доля фитнеса за само расстояние, пока машина не
# доехала до следующего чекпоинта: без него у эпизода, закончившегося ДО
# первого чекпоинта, фитнес был бы буквально 0 у любого генома, и эволюции
# не за что было бы отличить "проехал немного и красиво" от "не сдвинулся с
# места вообще". 0.001 подобрано так, чтобы полностью проехать один разрыв
# между чекпоинтами (~250px после уплотнения в file_worker.parse_track) без
# пересечения линии стоило ~0.25 - заметно меньше, чем реальные +1 за сам
# чекпоинт (см. GameEnvironment.resolve), но не ноль.
DISTANCE_CONSOLATION_SCALE = 0.001

# Компас (_heading_error_to_next_checkpoint) целился ТОЧНО в середину
# следующего чекпоинта - при плотных чекпоинтах (см. _densify_checkpoints в
# file_worker.py) это превращало езду в "от точки к точке": сеть целится в
# чекпоинт N, пересекает его, тут же перецеливается на N+1 (который обычно
# лежит с небольшим боковым смещением от плавной трассы) - на выходе
# заметный зигзаг вокруг сглаженной ("идеальной") линии, хотя сама эта линия
# в фитнес/сеть не подключена вообще (только визуальный оверлей и статистика
# в панели - см. CLAUDE.md). CHECKPOINT_LOOKAHEAD_WEIGHT смешивает цель со
# СЛЕДУЮЩИМИ за следующим воротами (см. _gate_midpoint) - компас указывает
# не точно на N, а на взвешенную точку между N и N+1, сглаживая сигнал через
# стык чекпоинтов, а не убирая направляющий сигнал совсем (полное удаление
# компаса рисковало вернуть застревание обучения, которое он и решал).
CHECKPOINT_LOOKAHEAD_WEIGHT = 0.6


class PhyCar(Car):
    def __init__(self, screen: Screen, visible, car_size, space=None):
        car_image = pygame.image.load("./assets/car.png")
        car_image = pygame.transform.scale(car_image, car_size)
        car_image = pygame.transform.rotate(car_image, -90)
        self.car_image = car_image

        self.tick_count = 0
        self.lap_start_tick = 0
        self.best_lap_time = 0
        self.position_history = []  # для отрисовки пройденного пути (см. update())
        self.cl_count = 0
        self.fitness = 0
        self.lap_count = 0
        self.next_checkpoint_index = 0
        # Читаем текущие модульные значения при создании машины (а не жёстко
        # захардкоженные) - так изменения настроек в UI-панели (мощность,
        # масса) подхватываются НОВЫМИ машинами следующей группы/поколения,
        # как MAX_VISIBLE/GROUP_SIZE в neat_runner/main.py.
        self.mass = CAR_MASS
        self.engine_power_hp = ENGINE_POWER_HP
        self.car_size = car_size

        self.damping_rate = 0.93  # Коэффициент гашения скорости

        self.moment = pymunk.moment_for_box(self.mass, self.car_size)

        body = pymunk.Body(self.mass, self.moment)
        body.position = get_midpoint(screen.start_line)
        shape = pymunk.Poly.create_box(body, self.car_size)

        self.car_rect = car_image.get_rect(center=body.position)

        shape.friction = 0.25

        self.screen = screen

        # Если space не передан - машина сама себе владелец физики (ручной
        # режим/одиночный запуск): создаёт свой Space и сама шагает его в
        # update(). Если space передан извне (групповое обучение) - несколько
        # машин делят один Space, и шаг физики делает вызывающий код один раз
        # на весь тик (см. car_racer/neat_runner/main.py), а не каждая машина
        # по отдельности - иначе общий Space продвигался бы в N раз быстрее,
        # чем нужно, при N активных машинах в группе.
        if space is None:
            self.space = pymunk.Space()
            self.space.gravity = (0, 0)
            self.owns_space = True
        else:
            self.space = space
            self.owns_space = False
        self.space.add(body, shape)

        self.body = body
        # Кэш геометрии лучей-сенсоров (мировые координаты), заполняется в
        # get_inputs_for_network() - см. draw_sensors() ниже про то, зачем
        # рисовать по кэшу, а не сразу внутри get_inputs_for_network().
        self._sensor_debug = []
        self.x, self.y = self.car_size
        # Квадрат со стороной = ширина машины (self.x), а не длина (self.y) и
        # без учёта поворота (body.angle) - грубое, но достаточное для
        # детекции пересечения линий чекпоинтов/финиша приближение (НЕ для
        # столкновения со стеной - там отдельный collision_radius по
        # окружности, см. check_collision_with_track ниже); осознанное
        # упрощение, трогать форму/размер не нужно. Центр рамки - ровно
        # body.position (раньше был смещён на -x//3 при стороне x, то есть
        # несимметрично - например, x=15 давало смещение -5 при половине
        # стороны 7.5).
        self.collistion_rect = pygame.Rect(self.body.position.x - self.x / 2,
                                           self.body.position.y - self.x / 2,
                                           self.x, self.x)
        self.collision_radius = self.x * math.sqrt(2) / 2  # см. check_collision_with_track
        self.perpendicular_angle(self.screen.start_line)
        self.visible = visible

        # --- Состояние новой модели руля/сноса (см. константы выше) --------
        # steering_angle - текущий угол передних колёс (rad), плавно движется
        # к цели из turn(); velocity_heading - направление вектора скорости,
        # отстаёт от курса body.angle (угол скольжения, см. SLIP_ALIGN_*).
        self.steering_angle = 0.0
        self.velocity_heading = self.body.angle

        self.total_distance = 0.0  # Инициализация общего пройденного расстояния
        self.last_position = self.body.position  # Начальная позиция

        # throttle()/turn() больше не мутируют тело напрямую - они только
        # запоминают запрошенное действие ("pending"), а update() применяет
        # их СОВМЕСТНО через общий бюджет сцепления (см. _apply_controls).
        # Так throttle() и turn() остаются раздельными методами (интерфейс
        # Car не меняется, ручной режим тоже работает как раньше), но их
        # РЕЗУЛЬТАТ теперь взаимно ограничен, а не независим.
        self._pending_throttle_power = 0.0
        self._pending_turn_power = 0.0
        self._has_pending_throttle = False
        self._has_pending_turn = False

    def throttle(self, throttle_power):
        self._pending_throttle_power = throttle_power
        self._has_pending_throttle = True

    def turn(self, turn_power):
        self._pending_turn_power = turn_power
        self._has_pending_turn = True

    def _desired_speed(self, throttle_power, current_speed):
        """Целевая скорость от одного лишь газа/тормоза, без учёта сцепления
        с поворотом. Разгон под тягой ограничен ДВИГАТЕЛЬНЫМ потолком
        ускорения (`max_accel`, масштабируется мощностью/массой этой
        конкретной машины - см. комментарий у ENGINE_POWER_HP/CAR_MASS) - это
        именно ПОТОЛОК на ускорение, а не скорость "подтягивания" к целевой
        скорости, как было раньше (`effective_rate` - доля разницы до цели,
        проходимая за тик): при большом разрыве до цели (например, старт с
        места) старая модель подразумевала требуемое ускорение, пропорциональное
        ВСЕЙ этой разнице - оно почти при любой настройке мощности улетало
        далеко за GRIP_ACCEL и обрезалось кругом трения в _apply_controls ОДНИМ
        и тем же значением независимо от мощности, то есть "Мощность (л.с.)"
        на практике перестаёт на что-либо влиять уже начиная с ~5 л.с. при
        референсных 15 (проверено эмпирически). Явный потолок ускорения этого
        не допускает: ниже референсной мощности/массы ограничивает именно
        двигатель (мощность реально влияет на разгон), выше - потолок
        двигателя превышает GRIP_ACCEL и обрезает уже круг трения в
        _apply_controls (как и должно быть - двигатель не может "перебить"
        сцепление шин с асфальтом). Торможение - отдельно и НЕ зависит от
        мощности: тормозное ускорение ограничено сцеплением шин с асфальтом,
        а не мотором, и не зависит от массы (см. комментарий у
        ENGINE_POWER_HP/CAR_MASS)."""
        if throttle_power == 0:
            return current_speed
        clamped = max(0, min(1, throttle_power))
        if clamped > 0:
            target_speed = clamped * MAX_SPEED
            power_ratio = self.engine_power_hp / REFERENCE_POWER_HP
            mass_ratio = REFERENCE_MASS / self.mass
            max_accel = GRIP_ACCEL * power_ratio * mass_ratio
            new_speed = min(target_speed, current_speed + max_accel / TICK_RATE)
        else:
            new_speed = max(0.0, current_speed - BRAKE_RATE)
        return min(MAX_SPEED, new_speed)

    def _apply_controls(self):
        dt = 1.0 / TICK_RATE
        current_speed = self.body.velocity.length

        # 1) Руль: turn() задаёт ЦЕЛЬ руля, а сам угол поворачивается с конечной
        # скоростью STEERING_RATE (руль нельзя дёрнуть мгновенно - раньше за
        # это отвечал отдельный ручной "снос" UNDERSTEER_*).
        if self._has_pending_turn:
            steer_target = self._pending_turn_power * MAX_STEERING_ANGLE
            max_step = STEERING_RATE * dt
            delta = max(-max_step, min(max_step, steer_target - self.steering_angle))
            self.steering_angle += delta

        # 2) Продольное ускорение от газа/тормоза (лаг-модель двигателя, см.
        # _desired_speed) - в px/s^2, за этот тик.
        desired_speed = (self._desired_speed(self._pending_throttle_power, current_speed)
                         if self._has_pending_throttle else current_speed)
        lon_accel = (desired_speed - current_speed) * TICK_RATE

        # 3) Поперечное ускорение из руля: угловая скорость по кинематике
        # велосипеда ω = v / WHEELBASE * tan(δ), боковое ускорение a = v·ω.
        if current_speed > VELOCITY_EPSILON:
            yaw_rate = current_speed / WHEELBASE * math.tan(self.steering_angle)
        else:
            yaw_rate = 0.0
        lat_accel = current_speed * yaw_rate

        # 4) Круг трения: сумма продольного и поперечного ускорения ограничена
        # бюджетом GRIP_ACCEL - если сцепления не хватает на оба запроса разом,
        # ужимаем ОБА пропорционально (круг, а не отдельные лимиты).
        combined = math.hypot(lon_accel, lat_accel)
        if combined > GRIP_ACCEL:
            scale = GRIP_ACCEL / combined
            lon_accel *= scale
            lat_accel *= scale

        # 5) Применяем: скорость v += a_lon·dt, рысканье ω = a_lat / v.
        new_speed = max(0.0, min(MAX_SPEED, current_speed + lon_accel * dt))
        if current_speed > VELOCITY_EPSILON:
            new_angular = lat_accel / current_speed
        else:
            new_angular = 0.0
        new_angular = max(min(new_angular, ROTATE_POWER), -ROTATE_POWER)

        # 6) Снос: направление скорости догоняет курс не мгновенно (см.
        # SLIP_ALIGN_* выше). Чем выше скорость, тем медленнее прилипает -
        # угол скольжения между velocity_heading и body.angle растёт в крутом
        # повороте на скорости, и машина видимо "плывёт".
        align_rate = SLIP_ALIGN_GAIN / (1.0 + current_speed * SLIP_SPEED_FACTOR)
        heading_err = math.atan2(math.sin(self.body.angle - self.velocity_heading),
                                 math.cos(self.body.angle - self.velocity_heading))
        self.velocity_heading += heading_err * align_rate * dt

        self.body.velocity = pymunk.Vec2d(1, 0).rotated(self.velocity_heading) * new_speed
        self.body.angular_velocity = new_angular

    def update(self):
        # Если ни throttle(), ни turn() не вызывались в этом тике (например,
        # в ручном режиме при отпущенных клавишах - там рулит damping()) -
        # не трогаем скорость/угловую скорость через круг сцепления вообще,
        # как и раньше.
        if self._has_pending_throttle or self._has_pending_turn:
            self._apply_controls()
            self._has_pending_throttle = False
            self._has_pending_turn = False

        if self.owns_space:
            self.space.step(1 / TICK_RATE)
        self.tick_count += 1
        self.collistion_rect = pygame.Rect(self.body.position.x - self.x / 2,
                                           self.body.position.y - self.x / 2,
                                           self.x, self.x)

        # Вычисляем пройденное расстояние
        current_position = self.body.position
        distance_traveled = (current_position - self.last_position).length
        self.total_distance += distance_traveled
        self.last_position = current_position

        self.position_history.append((current_position.x, current_position.y))

    def get_distance(self):
        return self.total_distance

    def damping(self, throttle: bool, turning: bool):
        if throttle:
            self.body.velocity *= self.damping_rate
        if turning:
            self.body.angular_velocity *= self.damping_rate
        self.body.velocity = pymunk.Vec2d(1, 0).rotated(self.body.angle) * self.get_speed()

    def draw(self):
        if not self.visible:
            return
        # Сенсоры рисуются ДО спрайта машины, чтобы машина была видна поверх
        # собственных лучей, а не под ними - см. draw_sensors().
        self.draw_sensors()
        # Позиция и повёрнутый спрайт машины - мировые координаты/размер
        # проходят через камеру (car_racer/screen/camera.py) перед рисовкой:
        # rotozoom вместо rotate, чтобы спрайт ещё и масштабировался под
        # текущий zoom камеры, а не только поворачивался. Мировые атрибуты
        # машины (self.body.position/angle) камера не трогает вообще.
        camera = self.screen.camera
        rotated_image = pygame.transform.rotozoom(self.car_image, -math.degrees(self.body.angle), camera.zoom)
        screen_pos = camera.world_to_screen(self.body.position)
        self.car_rect = rotated_image.get_rect(center=screen_pos)
        self.screen.get_window().blit(rotated_image, self.car_rect.topleft)
        # pygame.draw.rect(self.screen.get_window(), (255, 255, 255), self.collistion_rect)

    def get_lap_time(self):
        return self.best_lap_time

    def get_fitness(self):
        return self.fitness

    def get_cl(self):
        return self.cl_count

    def add_fitness(self, fitness):
        self.fitness += fitness

    def add_distance_consolation_fitness(self):
        """См. DISTANCE_CONSOLATION_SCALE. Раньше вызывалось только при
        столкновении со стеной (check_collision_with_track) - эпизод,
        закончившийся по ТАЙМАУТУ (GameEnvironment.decide()), вообще не
        получал этот бонус, хотя машина могла проехать ту же дистанцию, что
        и разбившаяся - несправедливая асимметрия между двумя способами
        закончить эпизод. Теперь вызывается из обоих мест одинаково."""
        self.fitness += self.get_distance() * DISTANCE_CONSOLATION_SCALE

    def get_laps(self):
        return self.lap_count

    def get_postion(self) -> (int, int):
        return self.body.position.x, self.body.position.y

    def get_speed(self) -> float:
        return self.body.velocity.length

    def draw_line(self, angle: int):
        # ЧИСТАЯ геометрия, без побочной отрисовки - direction_deg нужен
        # get_inputs_for_network() для реального cast_ray независимо от
        # видимости линий (см. draw_sensors ниже про то, где и почему теперь
        # рисуются сами линии).
        direction_deg = -math.degrees(self.body.angle) + angle
        return direction_deg

    def draw_sensors(self):
        """Рисует лучи-сенсоры и точки попадания из self._sensor_debug
        (заполняется в get_inputs_for_network(), см. там) - вызывается из
        draw(), т.е. ПОСЛЕ screen.draw_track() в рендер-блоке neat_runner/main.py.

        Раньше (до этого исправления) линии рисовались НЕМЕДЛЕННО внутри
        get_inputs_for_network(), которая вызывается из env.decide() - а
        decide() для всех машин группы происходит РАНЬШЕ screen.draw_track()
        в этом же тике (порядок: decide -> space.step -> resolve -> [камера] ->
        draw_track -> render всех машин -> present). draw_track() начинается с
        self.win.fill(...) - это стирало ВСЕ линии, нарисованные decide() этим
        же тиком, ДО того как кадр попадал в present(). Итог: лучи сенсоров
        физически не могли быть видны в реальном игровом цикле НИКОГДА (только
        в одноразовых тестовых скриптах, которые не вызывали draw_track()
        после get_inputs_for_network() и потому не воспроизводили баг) - хотя
        сам расчёт (cast_ray/distance, вход сети) всегда был корректен,
        это баг именно отрисовки. Кэширование мировых координат в
        get_inputs_for_network() и отрисовка из draw() (после draw_track(),
        как и спрайт машины) исправляет это без пересчёта луча."""
        if not (self.visible and self.screen.show_sensors):
            return
        camera = self.screen.camera
        for car_position, line_end_pos, hit_point in self._sensor_debug:
            pygame.draw.line(self.screen.get_window(), GRAY,
                             camera.world_to_screen(car_position), camera.world_to_screen(line_end_pos), 1)
            if hit_point is not None:
                pygame.draw.circle(self.screen.get_window(), WHITE,
                                   camera.world_to_screen(hit_point), camera.scale_length(3))

    def check_collision_with_track(self):
        pos_x, pos_y = self.body.position
        # Барьер "далеко за пределами трассы" - прямоугольник bounding box
        # ЭТОЙ трассы + отступ (см. Screen._recompute_world_bounds), а НЕ
        # фиксированные screen.screen_width/screen_height (2000x1200) как
        # раньше - трасса теперь может быть физически намного больше окна
        # рендера (points_xti_winter.txt после переезда на PX_PER_METER,
        # см. CLAUDE.md), и старая проверка ложно засчитывала бы выезд за
        # пределы на дальней части такой трассы. Это ВТОРИЧНЫЙ, грубый
        # барьер - основной детектор "разбился" ниже (расстояние до стены).
        min_x, min_y, max_x, max_y = self.screen.world_bounds
        if pos_x <= min_x or pos_x >= max_x or pos_y <= min_y or pos_y >= max_y:
            self.add_distance_consolation_fitness()
            return True

        # Радиус — половина диагонали квадратного collistion_rect (сторона
        # self.x): расстояние от центра до сегмента <= радиуса означает, что
        # сегмент задевает описанную вокруг машины окружность, которая
        # заведомо покрывает сам квадрат collistion_rect (немного шире, чем
        # точный тест pygame.Rect.clipline(), но при размере машины в
        # единицы-десятки пикселей разница не играет роли).
        distance = min_distance_to_segments(
            (pos_x, pos_y), self.screen.track_segments_start, self.screen.track_segments_end)
        if distance <= self.collision_radius:
            self.add_distance_consolation_fitness()
            return True
        return False

    def check_collision_with_checkpoint(self):
        if self.next_checkpoint_index >= len(self.screen.checkpoints_lines):
            return False
        line_start, line_end = self.screen.checkpoints_lines[self.next_checkpoint_index]
        if self.collistion_rect.clipline(line_start, line_end):
            self.next_checkpoint_index += 1
            self.cl_count += 1
            return True
        return False

    def check_collision_with_start(self):
        line_start, line_end = self.screen.start_line
        if (self.collistion_rect.clipline(line_start, line_end) and
                self.next_checkpoint_index == len(self.screen.checkpoints_lines)):
            self.next_checkpoint_index = 0
            self.lap_count += 1
            self.best_lap_time = (self.tick_count - self.lap_start_tick) / TICK_RATE
            self.lap_start_tick = self.tick_count
            # Иначе draw_path (см. neat_runner/main.py) рисовал бы путь ВСЕХ
            # кругов подряд одной линией - копится без ограничения, чем
            # дольше живёт машина. Новый круг - новая линия с нуля.
            self.position_history = []
            return True
        return False

    def _gate_midpoint(self, index):
        """Середина ворот (чекпоинта) с этим индексом, либо линии старта,
        если индекс за пределами списка чекпоинтов (после последнего ворота
        следующая цель - финиш) - общий хэлпер для текущей цели компаса и
        точки "заглядывания вперёд" (см. _heading_error_to_next_checkpoint)."""
        checkpoints = self.screen.checkpoints_lines
        if index < len(checkpoints):
            p1, p2 = checkpoints[index]
        else:
            p1, p2 = self.screen.start_line
        return get_midpoint((p1, p2))

    def _heading_error_to_next_checkpoint(self):
        """Угол между направлением машины и направлением на СГЛАЖЕННУЮ цель
        (см. CHECKPOINT_LOOKAHEAD_WEIGHT выше - смесь середины следующего
        чекпоинта и того, что идёт ЗА ним, а не точное прицеливание в один
        следующий чекпоинт), нормализован в [-1, 1]. Раньше сеть видела
        только 7 лучей-дальномеров до стен - на длинных прогонах между
        чекпоинтами (особенно на сложных трассах, где нужный поворот виден
        лучами слишком поздно) у неё не было НИКАКОГО сигнала о том, куда
        вообще едет трасса, только реакция на стены по факту. Это не
        замена лучам (стены всё равно нужны, чтобы не влетать в них), а
        компас "куда следующая цель" - как GPS-стрелка на приборке.
        car_position/atan2 - в тех же мировых координатах и той же
        конвенции угла, что и body.angle (см. calculate_end_pos/cast_ray:
        forward-вектор машины = (cos(angle), sin(angle)), поэтому здесь не
        нужен минус перед sin, в отличие от direction_deg в draw_line)."""
        idx = self.next_checkpoint_index
        n = len(self.screen.checkpoints_lines)
        target_x, target_y = self._gate_midpoint(idx)
        # Lookahead: смешиваем текущую цель со СЛЕДУЮЩЕЙ, чтобы сгладить курс.
        # Для обычного чекпоинта следующая - чекпоинт idx+1 (для последнего -
        # финиш, т.к. _gate_midpoint(n) возвращает start_line). Для САМОГО
        # финиша (idx == n) следующая цель - ПЕРВЫЙ чекпоинт нового круга:
        # иначе компас целился бы ТОЧНО в точку на линии старта, сигнал курса
        # становился нестабильным прямо перед финишем, и сеть выучивала
        # тормозить/зависать, а не проезжать финиш насквозь.
        if idx < n:
            look_x, look_y = self._gate_midpoint(idx + 1)
        else:
            look_x, look_y = self._gate_midpoint(0)
        w = CHECKPOINT_LOOKAHEAD_WEIGHT
        target_x = target_x * w + look_x * (1 - w)
        target_y = target_y * w + look_y * (1 - w)
        car_x, car_y = self.get_postion()
        target_angle = math.atan2(target_y - car_y, target_x - car_x)
        heading_error = target_angle - self.body.angle
        heading_error = math.atan2(math.sin(heading_error), math.cos(heading_error))
        return heading_error / math.pi

    def get_inputs_for_network(self):
        # Нормализуем угол в [-1, 1] (не накапливается при многократных оборотах)
        normalized_angle = math.atan2(math.sin(self.body.angle), math.cos(self.body.angle)) / math.pi
        normalized_speed = min(self.get_speed() / MAX_SPEED, 1.0)
        inputs = [normalized_angle, normalized_speed, self._heading_error_to_next_checkpoint()]

        car_position = self.get_postion()
        seg_starts = self.screen.track_segments_start
        seg_ends = self.screen.track_segments_end

        # Кэш для draw_sensors() (см. там) - НЕ рисуем прямо здесь: decide()
        # (откуда вызывается get_inputs_for_network) происходит раньше
        # screen.draw_track() в этом же тике, а тот делает fill() и стёр бы
        # любую отрисовку отсюда до того, как кадр показан (см. draw_sensors).
        self._sensor_debug = []
        for angle in [-150, -90, -45, 0, 45, 90, 150]:
            direction_deg = self.draw_line(angle)
            distance, hit_point = cast_ray(car_position, direction_deg, SENSOR_RANGE, seg_starts, seg_ends)
            line_end_pos = calculate_end_pos(car_position, direction_deg, SENSOR_RANGE)
            self._sensor_debug.append((car_position, line_end_pos, hit_point))
            inputs.append(distance / SENSOR_RANGE)

        return inputs

    def perpendicular_angle(self, line):
        # Создаем вектора из точек
        p1, p2 = line
        vec = pymunk.Vec2d(p2[0] - p1[0], p2[1] - p1[1])

        # Угол вектора относительно оси x
        angle = vec.angle  # Это возвращает угол в радианах относительно оси x

        self.body.angle = angle + math.pi / 2  # 90 градусов в радианах
