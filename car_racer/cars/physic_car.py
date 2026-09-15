import math

import pygame
import pymunk

from car_racer.cars.abs_car import Car
from car_racer.constants import GRAY, WHITE, SENSOR_RANGE, TICK_RATE
from car_racer.screen.screen import Screen
from helpers.calculate import calculate_end_pos, get_midpoint, cast_ray, min_distance_to_segments

CAR_HEIGHT = 80
CAR_WIDTH = 50
VELOCITY_EPSILON = 0.1
ROTATE_POWER = 3.0  # Сила поворота
THROTTLE_POWER = 200  # Сила тяги
MAX_SPEED = 400  # Установи подходящее значение
SPEED_EFFECT = 0.3  # Чем больше значение, тем меньше поворот на высокой скорости
ACCELERATION_RATE = 0.2
BRAKE_RATE = 15

# --- Модель сцепления (круг трения), приближение картинга на асфальте ------
# Раньше throttle() и turn() были полностью независимы: сеть могла жать газ в
# пол ровно в середине шпильки без всякого штрафа. У реального картинга на
# асфальте доступное сцепление шин ограничивает СУММУ продольного (разгон/
# торможение) и поперечного (поворот) ускорения - выжать оба на максимум
# одновременно физически нельзя.
#
# GRIP_ACCEL - условный бюджет доступного ускорения в px/s^2 (единой
# калибровки px->метры в проекте нет нигде). Подобран НЕ как попало: старая
# лаг-модель разгона (ACCELERATION_RATE) сама по себе даёт пиковое продольное
# ускорение ~2400 px/s^2 при большом рассогласовании скоростей (например,
# полный газ с полной остановки) - если взять GRIP_ACCEL заметно меньше этого,
# круг трения душит вообще любой резкий разгон по прямой, даже без поворота,
# что не про сцепление, а просто урезает динамику. 2000 выбрано так, чтобы:
# чистый разгон по прямой почти не подрезался (кроме самого первого тика от
# полной остановки - разумный аналог пробуксовки), чистый поворот на макс.
# скорости (до ~1200 px/s^2 при ROTATE_POWER=3 и MAX_SPEED=400) не подрезался
# вовсе, а вот КОМБИНАЦИЯ жёсткого газа и жёсткого руля (особенно на выходе
# из медленного поворота) - заметно ограничивается, что и есть нужный эффект.
#
# GRIP_ACCEL_PER_G - чисто для отображения в UI-настройках в узнаваемых "g"
# (стандартный автоспортивный термин: "машина держит 1.5g в повороте"), а не
# в голом px/s^2. Подобрано так, чтобы дефолтные 2000 px/s^2 показывались как
# 1.5g (правдоподобное значение для картинга на асфальте) - это ЭТИКЕТКА для
# слайдера, а не независимая калибровка px->метры (её как не было, так и нет).
GRIP_ACCEL = 2000.0
GRIP_ACCEL_PER_G = GRIP_ACCEL / 1.5

# Картинг ездит на "спуле" - жёсткой задней оси без дифференциала: в повороте
# внутреннее заднее колесо вынуждено либо проскальзывать, либо подвисать,
# из-за чего крутые повороты на малой скорости даются заметно хуже, чем на
# ходу (в отличие от машины с дифференциалом). Ниже порога скорости
# эффективность руля дополнительно падает, линейно доходя до минимума на
# нулевой скорости.
NO_DIFF_SPEED_THRESHOLD = 60.0
NO_DIFF_MIN_EFFECTIVENESS = 0.4

# --- Снос/занос/скраб от РЕЗКИХ воздействий ------------------------------
# Три эффекта поверх круга трения выше - каждый реагирует на то, НАСКОЛЬКО
# РЕЗКО (не просто насколько сильно) меняется газ/руль между тиками,
# приближая поведение на пределе сцепления к реальному вместо простого
# "меньше скорости/поворота при том же запросе".

# 1) Снос (understeer): резкий скачок руля за один тик снижает эффективность
# поворота именно НА ЭТОТ тик - передние шины не успевают "зацепиться" за
# новый угол, руль воспринимается смазанно, машина продолжает по кривой шире
# скомандованной. UNDERSTEER_RATE_THRESHOLD - скачок |Δturn_power| за тик
# (сеть отдаёт примерно [-1, 1]), после которого эффект выходит на максимум;
# UNDERSTEER_MIN_EFFECTIVENESS - до какой доли падает эффективность руля при
# самом резком скачке (по аналогии с NO_DIFF_MIN_EFFECTIVENESS выше).
UNDERSTEER_RATE_THRESHOLD = 1.0
UNDERSTEER_MIN_EFFECTIVENESS = 0.4

# 2) Занос (oversteer): резкий скачок ГАЗА при уже ненулевой угловой скорости
# (машина уже в повороте) добавляет ЛИШНЕЕ вращение В ТУ ЖЕ СТОРОНУ поверх
# того, что просил руль - задняя ось теряет сцепление под тягой. В отличие
# от круга трения этот довесок НЕ ограничен GRIP_ACCEL (это и есть потеря
# сцепления, а не законный манёвр в его пределах) - только общим потолком
# ROTATE_POWER в конце _apply_controls. OVERSTEER_MIN_ANGULAR - порог текущей
# угловой скорости, ниже которого считаем "едем прямо" и занос не запускаем
# (иначе резкий старт с места давал бы случайный спин на пустом месте).
# OVERSTEER_THROTTLE_THRESHOLD - на сколько должен скакнуть газ за тик,
# прежде чем начнётся занос. OVERSTEER_STRENGTH - сила эффекта.
OVERSTEER_MIN_ANGULAR = 0.3
OVERSTEER_THROTTLE_THRESHOLD = 0.3
OVERSTEER_STRENGTH = 2.0

# 3) Скраб: поворот сам по себе гасит скорость (сцепление уходит не только в
# поперечное ускорение, но и в потерю хода), даже В ПРЕДЕЛАХ бюджета круга
# трения - раньше манёвр "внутри лимита" вообще не стоил скорости, что
# физически неверно (гоночная линия существует именно потому, что скорость в
# повороте теряется). STEER_SCRUB_COEFF подобран, чтобы на близком к
# максимуму руле и высокой скорости скраб был заметным (~8-9%/с при
# непрерывном руле в пол на макс. скорости), но не превращал каждый поворот
# в остановку.
STEER_SCRUB_COEFF = 0.03

# --- Мощность и масса --------------------------------------------------
# Разгон под тягой физически зависит от мощности двигателя и массы (F=ma,
# при этом мощность P~F*v - тяжелее машина/слабее мотор -> медленнее разгон).
# А вот торможение и сцепление в повороте (GRIP_ACCEL выше) НЕ зависят от
# массы: максимальное тормозное/поперечное ускорение a=μg определяется только
# трением шин о асфальт и НЕ зависит от того, тяжёлая машина или лёгкая (сила
# трения и масса сокращаются) - поэтому масса ниже влияет только на разгон.
#
# ENGINE_POWER_HP/CAR_MASS выражены в узнаваемых единицах (л.с., кг) для
# наглядности в UI-настройках, но, как и GRIP_ACCEL_PER_G выше, это не
# независимая физическая калибровка (в проекте её нет и для длины/времени) -
# просто дефолты подобраны так, чтобы РЕФЕРЕНСНЫЕ значения (REFERENCE_*)
# воспроизводили прежнее ощущение разгона (ACCELERATION_RATE как было), а
# дальше от них масштабирование линейное и физически осмысленное.
ENGINE_POWER_HP = 15.0      # типичный прокатный картинг (5-40 л.с. - разумный диапазон)
REFERENCE_POWER_HP = 15.0   # мощность, при которой разгон == прежнему ACCELERATION_RATE

CAR_MASS = 1.0              # масса в "игровых" единицах pymunk (для body/moment)
REFERENCE_MASS = 1.0        # масса, при которой разгон == прежнему ACCELERATION_RATE
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
        self.draw_speed_vectore = True
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

        # Значения газа/руля из ПРЕДЫДУЩЕГО тика, где они реально применялись
        # - нужны, чтобы отличить "резко дёрнули" от "плавно держат" (снос/
        # занос выше реагируют именно на скачок, а не на абсолютную величину).
        self._prev_throttle_power = 0.0
        self._prev_turn_power = 0.0

    def throttle(self, throttle_power):
        self._pending_throttle_power = throttle_power
        self._has_pending_throttle = True

    def turn(self, turn_power):
        self._pending_turn_power = turn_power
        self._has_pending_turn = True

    def _desired_speed(self, throttle_power, current_speed):
        """Целевая скорость от одного лишь газа/тормоза, без учёта сцепления
        с поворотом. Разгон под тягой масштабируется мощностью/массой этой
        конкретной машины (F=ma, P~F*v); торможение - нет: тормозное
        ускорение ограничено сцеплением шин с асфальтом, а не мотором, и не
        зависит от массы (см. комментарий у ENGINE_POWER_HP/CAR_MASS)."""
        if throttle_power == 0:
            return current_speed
        clamped = max(0, min(1, throttle_power))
        if clamped > 0:
            target_speed = clamped * MAX_SPEED
            power_ratio = self.engine_power_hp / REFERENCE_POWER_HP
            mass_ratio = REFERENCE_MASS / self.mass
            effective_rate = min(1.0, ACCELERATION_RATE * power_ratio * mass_ratio)
            new_speed = current_speed + (target_speed - current_speed) * effective_rate
        else:
            new_speed = max(0.0, current_speed - BRAKE_RATE)
        return min(MAX_SPEED, new_speed)

    def _desired_angular_velocity(self, turn_power, current_speed, current_angular):
        """Целевая угловая скорость от одного лишь руля, без учёта сцепления
        с газом - логика как в прежнем turn(), плюс штраф за отсутствие
        дифференциала на малой скорости (см. NO_DIFF_*)."""
        if current_speed < VELOCITY_EPSILON:
            return current_angular

        turn_effectiveness = max(0.05, 1 - SPEED_EFFECT * (current_speed / MAX_SPEED))
        if current_speed < NO_DIFF_SPEED_THRESHOLD:
            no_diff_factor = (NO_DIFF_MIN_EFFECTIVENESS
                              + (1 - NO_DIFF_MIN_EFFECTIVENESS) * (current_speed / NO_DIFF_SPEED_THRESHOLD))
            turn_effectiveness *= no_diff_factor

        # Снос (understeer) - см. UNDERSTEER_* выше: чем резче скачок руля со
        # прошлого тика, тем меньше эффективность поворота именно сейчас.
        turn_power_delta = abs(turn_power - self._prev_turn_power)
        understeer_factor = 1.0 - (1.0 - UNDERSTEER_MIN_EFFECTIVENESS) * min(
            1.0, turn_power_delta / UNDERSTEER_RATE_THRESHOLD)
        turn_effectiveness *= understeer_factor

        if turn_power == 0:
            return current_angular
        angular_change = turn_power * ROTATE_POWER * turn_effectiveness
        new_angular = current_angular + angular_change
        return max(min(new_angular, ROTATE_POWER), -ROTATE_POWER)

    def _apply_controls(self):
        current_speed = self.body.velocity.length
        current_angular = self.body.angular_velocity

        desired_speed = (self._desired_speed(self._pending_throttle_power, current_speed)
                         if self._has_pending_throttle else current_speed)
        desired_angular = (self._desired_angular_velocity(self._pending_turn_power, current_speed, current_angular)
                           if self._has_pending_turn else current_angular)

        # Требуемые этим тиком ускорения: продольное - из изменения скорости,
        # поперечное (центростремительное) - из v*w при текущей скорости.
        lon_accel = (desired_speed - current_speed) * TICK_RATE
        lat_accel = desired_angular * current_speed

        combined = math.hypot(lon_accel, lat_accel)
        if combined > GRIP_ACCEL:
            # Сцепления не хватает на оба запроса разом - ужимаем ОБА
            # пропорционально общему бюджету (круг, а не отдельные лимиты)
            # вместо того, чтобы полностью отдать приоритет одному из них.
            scale = GRIP_ACCEL / combined
            lon_accel *= scale
            lat_accel *= scale
            desired_speed = current_speed + lon_accel / TICK_RATE
            if current_speed > VELOCITY_EPSILON:
                desired_angular = lat_accel / current_speed

        # Скраб (см. STEER_SCRUB_COEFF выше) - применяется к уже РАЗРЕШЁННОМУ
        # этим тиком повороту (desired_angular после круга трения), а не как
        # отдельная заявка К кругу трения: скраб - это следствие использования
        # поперечного сцепления, а не независимый запрос на него.
        scrub = STEER_SCRUB_COEFF * abs(desired_angular) * current_speed / TICK_RATE
        desired_speed = max(0.0, desired_speed - scrub)

        # Занос (oversteer, см. OVERSTEER_* выше) - резкий скачок газа, когда
        # машина уже в повороте, добавляет лишнее вращение В ТУ ЖЕ СТОРОНУ.
        # Специально НЕ участвует в круге трения выше (это потеря сцепления,
        # а не манёвр в его пределах) - ограничен только общим потолком
        # ROTATE_POWER сразу ниже.
        if self._has_pending_throttle and abs(current_angular) > OVERSTEER_MIN_ANGULAR:
            throttle_spike = self._pending_throttle_power - self._prev_throttle_power
            if throttle_spike > OVERSTEER_THROTTLE_THRESHOLD:
                kick = (OVERSTEER_STRENGTH * (throttle_spike - OVERSTEER_THROTTLE_THRESHOLD)
                        * math.copysign(1.0, current_angular) * (current_speed / MAX_SPEED))
                desired_angular += kick

        desired_speed = max(0.0, min(MAX_SPEED, desired_speed))
        desired_angular = max(min(desired_angular, ROTATE_POWER), -ROTATE_POWER)

        direction = pymunk.Vec2d(1, 0).rotated(self.body.angle)
        self.body.velocity = direction.normalized() * desired_speed
        self.body.angular_velocity = desired_angular

        if self._has_pending_throttle:
            self._prev_throttle_power = self._pending_throttle_power
        if self._has_pending_turn:
            self._prev_turn_power = self._pending_turn_power

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
        if self.draw_speed_vectore:
            # Отрисовка вектора силы
            if self.body.velocity.length > 0:
                end_pos_velocity = self.body.position + self.body.velocity.normalized() * self.get_speed()
                pygame.draw.line(self.screen.get_window(), (0, 0, 255), camera.world_to_screen(self.body.position),
                                 camera.world_to_screen(end_pos_velocity), camera.scale_length(3))

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
        target_x, target_y = self._gate_midpoint(idx)
        if idx < len(self.screen.checkpoints_lines):
            look_x, look_y = self._gate_midpoint(idx + 1)
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
