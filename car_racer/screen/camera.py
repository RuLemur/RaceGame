"""Камера игрового поля: пан (центр обзора) + зум для отрисовки трассы и машин
на логическом холсте `Screen.win`.

ВАЖНО: камера - ИСКЛЮЧИТЕЛЬНО про рендер. Мировые координаты (физика pymunk,
столкновения `check_collision_with_*`, сенсоры `get_inputs_for_network`/
`cast_ray`, границы `screen.screen_width/screen.screen_height`) камеру не
знают и не должны знать - трансформация применяется только непосредственно
перед вызовами `pygame.draw.*`/`Surface.blit` в рисующих методах Screen и
машин (car_racer/cars/physic_car.py::draw()/draw_line()/
get_inputs_for_network()).

Это отдельный, более "нижний" уровень, чем letterbox-масштабирование всего
логического холста под реальный размер окна в Screen.present() - тот механизм
не трогается вообще и ничего не знает про Camera.

UI-панель (car_racer/screen/ui_panel.py) камеру не использует - она рисуется
в своих логических координатах фиксированного холста, как и раньше.
"""

DEFAULT_ZOOM = 1.0
# MIN_ZOOM был 0.25 (достаточно, чтобы вписать points_xti_winter.txt,
# bbox ~6400x3250px, в игровое поле 2000x1200) - недостаточно для реальных
# кольцевых трасс (points_monza.txt/points_imola.txt, bbox ~29000x33000 и
# ~36600x19300px): на 0.25 видимый кусок мира (viewport/zoom) оказывался
# ЦЕЛИКОМ внутри пустой середины кольца - ни одной стены не видно, экран
# выглядел полностью чёрным (не баг рендера - трасса просто физически не
# попадала в кадр). 0.02 даёт видимый кусок 100000x60000px - с запасом
# вписывает самую большую трассу целиком (см. Screen.compute_fit_zoom).
MIN_ZOOM = 0.02
MAX_ZOOM = 2.5


class Camera:
    """Состояние: `center` - мировая точка, на которую сейчас смотрит камера
    (проецируется в центр видимой области игрового поля), `zoom` - множитель
    масштаба (> 1 - приближение, < 1 - отдаление).

    `viewport_width/height` - размер ИГРОВОГО ПОЛЯ на логическом холсте (без
    панели), т.е. `screen.screen_width/screen.screen_height` - именно этот
    прямоугольник камера показывает, панель ниже него камеры не касается.

    При `zoom=1` и `center` в центре игрового поля координатное
    преобразование - тождественное: `world_to_screen(p) == p` для любой точки
    поля. Это воспроизводит поведение до введения камеры (весь трек 1:1,
    без пана/зума) - используется, когда камера выключена/в режиме
    "показать весь трек" (см. `center_on_field`).
    """

    def __init__(self, viewport_width, viewport_height, zoom=DEFAULT_ZOOM):
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.zoom = zoom
        self.center = (viewport_width / 2, viewport_height / 2)

    def set_viewport(self, width, height):
        """Обновить размер игрового поля - вызывать, если он вообще может
        поменяться (сейчас screen_width/screen_height фиксированы на весь
        запуск, но метод на будущее и для явности)."""
        self.viewport_width = width
        self.viewport_height = height

    def center_on_field(self, world_center=None):
        """Центрировать камеру, не трогая zoom - режим "весь трек виден
        целиком" (Camera Follow выключен). `world_center` - мировая точка
        (см. Screen.track_center, центр bounding box трассы), на которую
        нужно центрироваться; если не передан - старое поведение
        ((viewport_width/2, viewport_height/2)), которое совпадает с
        реальным центром трассы ТОЛЬКО когда трасса физически вписана в тот
        же прямоугольник, что и viewport (как было раньше, пока трассы не
        стали крупнее рендер-канваса - см. CLAUDE.md про PX_PER_METER)."""
        if world_center is not None:
            self.center = world_center
        else:
            self.center = (self.viewport_width / 2, self.viewport_height / 2)

    def follow(self, world_point):
        """Центрировать камеру на мировой точке (например, позиции машины
        лучшего генома) - режим Camera Follow."""
        self.center = (world_point[0], world_point[1])

    def world_to_screen(self, point):
        """Мировая точка -> точка на логическом холсте (координаты
        игрового поля, те же, что принимает pygame.draw.*)."""
        cx, cy = self.center
        x, y = point
        return (
            (x - cx) * self.zoom + self.viewport_width / 2,
            (y - cy) * self.zoom + self.viewport_height / 2,
        )

    def world_to_screen_many(self, points):
        return [self.world_to_screen(p) for p in points]

    def screen_to_world(self, point):
        """Обратное преобразование - экранная (логическая) точка -> мировая.
        Не используется проверками столкновений/сенсорами (они не знают о
        камере вообще), но может пригодиться для будущего UI (например, клик
        по игровому полю)."""
        x, y = point
        cx, cy = self.center
        return (
            (x - self.viewport_width / 2) / self.zoom + cx,
            (y - self.viewport_height / 2) / self.zoom + cy,
        )

    def scale_length(self, length):
        """Масштабировать линейную величину (радиус, толщину линии) под
        текущий zoom, с минимумом в 1px, чтобы совсем не пропадать при
        сильном отдалении."""
        return max(1, round(length * self.zoom))
