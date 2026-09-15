"""Правая UI-панель окна игры: статистика обучения + кликабельные элементы
управления (пауза, рестарт, выбор трассы, числовые параметры обучения).

Вынесено из screen.py, чтобы не разрастать его - простые pygame-виджеты без
сторонних UI-библиотек (в духе Drawer.draw_button из helpers/draw_track.py).

Раньше это была горизонтальная полоса внизу окна (см. историю правок) -
перенесена в вертикальную колонку справа, т.к. Camera Follow может утащить
вид камеры куда угодно по треку, и полноширинная нижняя полоса тогда либо
перекрывала бы часть игрового поля, либо требовала бы отдельного расчёта, что
именно перекрыто. Вертикальная колонка фиксированной ширины справа не мешает
камере панорамировать по всей высоте поля.

Панель ПОЛУПРОЗРАЧНАЯ (см. draw()): фон и все виджеты рисуются на временной
pygame.Surface(..., pygame.SRCALPHA) размером с self.rect и блитятся на
основной холст одним вызовом - так альфа-канал корректно смешивается с тем,
что нарисовано под панелью (трасса), независимо от того, что сам self.win
обычной (не SRCALPHA) поверхностью. Единственное исключение - выпадающий
список трасс (см. _draw_track_dropdown): рисуется прямо на основной
поверхности, полностью непрозрачным, чтобы не обрезаться границами панели,
если список вылезет за её нижний край.
"""
import glob
import os
import time

import pygame

from car_racer.constants import PX_PER_METER
from car_racer.file_manager.file_worker import POINTS_DIR
from car_racer.screen.camera import DEFAULT_ZOOM, MIN_ZOOM, MAX_ZOOM

PANEL_WIDTH = 360
SCROLL_STEP = 44  # px за одно деление колеса мыши, см. UIPanel.handle_event
SCROLLBAR_COLOR = (255, 255, 255, 90)
SCROLLBAR_WIDTH = 4

PADDING = 16
SECTION_GAP = 12
HEADER_GAP = 6
BUTTON_H = 32
BUTTON_GAP = 6
FIELD_H = 26
FIELD_ROW_GAP = 8
COLUMN_GAP = 12

# Полупрозрачная тёмная база - альфа даёт трассе просвечивать сквозь панель.
PANEL_BG = (16, 18, 24, 218)
PANEL_BORDER = (255, 255, 255, 40)
SECTION_DIVIDER = (255, 255, 255, 26)
TITLE_COLOR = (235, 238, 245)
TITLE_DIVIDER = (255, 255, 255, 55)
HEADER_COLOR = (130, 190, 255)
TEXT_COLOR = (222, 226, 233)
TEXT_MUTED = (150, 156, 168)
PAUSED_COLOR = (255, 176, 90)

BUTTON_COLOR = (54, 58, 74, 230)
BUTTON_HOVER_COLOR = (78, 84, 108, 236)
BUTTON_ACTIVE_COLOR = (44, 138, 104, 240)
BUTTON_BORDER = (255, 255, 255, 34)
BUTTON_TEXT_COLOR = (240, 242, 248)
BUTTON_SHADOW = (0, 0, 0, 65)

FIELD_BG = (28, 30, 38, 232)
FIELD_BORDER = (255, 255, 255, 28)
FIELD_BORDER_FOCUS = (110, 172, 255, 255)
FIELD_BORDER_INVALID = (232, 96, 96, 255)

SLIDER_TRACK_BG = (28, 30, 38, 220)
SLIDER_TRACK_BORDER = (255, 255, 255, 28)
SLIDER_KNOB = (150, 158, 178, 255)
SLIDER_KNOB_ACTIVE = (110, 172, 255, 255)

CONFIRM_TIMEOUT = 3.0  # секунд, за которые нужно подтвердить Restart Training
INVALID_FLASH_TIMEOUT = 1.0  # секунд, на которые поле подсвечивается красным
                              # после отклонённого невалидного ввода


class Button:
    """Простая кликабельная кнопка-прямоугольник с опциональным toggle-режимом.

    `compact` - использовать small_font вместо обычного при отрисовке (см.
    UIPanel.draw) - нужен только track_button: имя файла трассы плюс префикс
    "Track: " не всегда помещается по ширине панели обычным шрифтом.
    """

    def __init__(self, rect, label, on_click=None, toggle=False, active_label=None, compact=False):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.on_click = on_click
        self.toggle = toggle
        self.active = False
        self.active_label = active_label or label
        self.hovered = False
        self.compact = compact

    def handle_event(self, event) -> bool:
        """Обрабатывает одно pygame-событие. Возвращает True, если клик пришёлся
        по этой кнопке (событие "потреблено")."""
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                if self.toggle:
                    self.active = not self.active
                if self.on_click:
                    self.on_click()
                return True
        return False

    def current_label(self):
        return self.active_label if (self.toggle and self.active) else self.label

    def draw(self, surface, font, offset=(0, 0)):
        rect = self.rect.move(-offset[0], -offset[1])
        if self.toggle and self.active:
            color = BUTTON_ACTIVE_COLOR
        elif self.hovered:
            color = BUTTON_HOVER_COLOR
        else:
            color = BUTTON_COLOR
        pygame.draw.rect(surface, BUTTON_SHADOW, rect.move(0, 2), border_radius=8)
        pygame.draw.rect(surface, color, rect, border_radius=8)
        pygame.draw.rect(surface, BUTTON_BORDER, rect, width=1, border_radius=8)
        text_surf = font.render(self.current_label(), True, BUTTON_TEXT_COLOR)
        text_rect = text_surf.get_rect(center=rect.center)
        surface.blit(text_surf, text_rect)


class Slider:
    """Горизонтальный слайдер с перетаскиваемым мышью бегунком - используется
    для camera.zoom (см. UIPanel._build_camera_section). Виджет целиком
    (rect) делится на три части: подпись слева, дорожка с бегунком посередине,
    текущее значение справа - `label_width`/`value_width` задают ширину крайних
    частей, дорожка занимает всё, что осталось.

    Поведение: MOUSEBUTTONDOWN по дорожке/бегунку начинает перетаскивание и
    сразу переставляет бегунок под курсor, MOUSEMOTION двигает его, пока
    зажата кнопка, MOUSEBUTTONUP отпускает - в отличие от TextField, значение
    применяется (`on_change`) непрерывно во время перетаскивания, а не только
    по подтверждению, чтобы зум менялся в реальном времени.
    """

    def __init__(self, rect, label, min_value, max_value, initial_value, on_change=None,
                 value_format="{:.2f}x", label_width=90, value_width=60):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.min_value = min_value
        self.max_value = max_value
        self.value = initial_value
        self.on_change = on_change
        self.value_format = value_format
        self.dragging = False
        self.knob_radius = 8
        self.track_rect = pygame.Rect(self.rect.x + label_width, self.rect.y,
                                       max(1, self.rect.width - label_width - value_width), self.rect.height)

    def _knob_x(self):
        span = self.max_value - self.min_value
        frac = 0.0 if span == 0 else (self.value - self.min_value) / span
        frac = max(0.0, min(1.0, frac))
        return self.track_rect.x + frac * self.track_rect.width

    def _value_from_x(self, x):
        span = self.max_value - self.min_value
        frac = (x - self.track_rect.x) / self.track_rect.width if self.track_rect.width else 0.0
        frac = max(0.0, min(1.0, frac))
        return self.min_value + frac * span

    def set_value(self, value):
        """Синхронизировать значение без вызова on_change - по аналогии с
        TextField.set_value (используется при программной установке значения
        по умолчанию, не как реакция на действие пользователя)."""
        self.value = max(self.min_value, min(self.max_value, value))

    def _hit_rect(self):
        # Дорожка + небольшой запас по вертикали, чтобы попадать по бегунку
        # было легче, чем только строго по кругу радиуса knob_radius.
        pad = self.knob_radius
        return pygame.Rect(self.track_rect.x - pad, self.rect.y - pad,
                            self.track_rect.width + 2 * pad, self.rect.height + 2 * pad)

    def handle_event(self, event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._hit_rect().collidepoint(event.pos):
                self.dragging = True
                self.value = self._value_from_x(event.pos[0])
                if self.on_change:
                    self.on_change(self.value)
                return True
        elif event.type == pygame.MOUSEMOTION and self.dragging:
            self.value = self._value_from_x(event.pos[0])
            if self.on_change:
                self.on_change(self.value)
            return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.dragging:
                self.dragging = False
                return True
        return False

    def draw(self, surface, font, label_font, offset=(0, 0)):
        rect = self.rect.move(-offset[0], -offset[1])
        track_rect = self.track_rect.move(-offset[0], -offset[1])

        label_surf = label_font.render(self.label, True, TEXT_COLOR)
        surface.blit(label_surf, (rect.x, rect.centery - label_surf.get_height() // 2))

        track_y = track_rect.centery
        line_rect = pygame.Rect(track_rect.x, track_y - 2, track_rect.width, 4)
        pygame.draw.rect(surface, SLIDER_TRACK_BG, line_rect, border_radius=2)
        pygame.draw.rect(surface, SLIDER_TRACK_BORDER, line_rect, width=1, border_radius=2)

        knob_x = self._knob_x() - offset[0]
        knob_color = SLIDER_KNOB_ACTIVE if self.dragging else SLIDER_KNOB
        pygame.draw.circle(surface, knob_color, (int(knob_x), track_y), self.knob_radius)
        pygame.draw.circle(surface, PANEL_BORDER, (int(knob_x), track_y), self.knob_radius, width=1)

        value_surf = font.render(self.value_format.format(self.value), True, TEXT_COLOR)
        surface.blit(value_surf, (track_rect.right + 10, rect.centery - value_surf.get_height() // 2))


class TextField:
    """Переиспользуемый виджет однострочного числового поля ввода
    (положительное число в заданных границах, целое или с фиксированным
    числом знаков после запятой).

    Поведение: клик по полю - фокус (подсветка синей рамкой), клик мимо или
    Enter - подтверждение введённого значения, Escape - отмена редактирования.
    Невалидный ввод (не число / вне границ / пусто) не применяется - поле
    откатывается к последнему валидному значению и на INVALID_FLASH_TIMEOUT
    секунд подсвечивается красной рамкой, чтобы было видно, что ввод не принят.

    `label` может содержать "\n" - тогда рисуется несколькими строками над
    полем (используется для длинных подписей вроде подсказки про Restart
    Training у pop_size). UIPanel всегда использует ровно 2 строки - см.
    _label_block_h() там же, где резервируется место под подпись в layout'е.

    `decimals` - 0 (по умолчанию) для целых чисел, как было раньше; 1+ чтобы
    разрешить точку и заданное число знаков после неё (например, сцепление в
    "g" вида 1.5 - целочисленным полем такое не выразить).
    """

    def __init__(self, rect, label, initial_value, min_value=1, max_value=None, on_confirm=None, decimals=0):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.min_value = min_value
        self.max_value = max_value
        self.on_confirm = on_confirm
        self.decimals = decimals
        self._last_valid = self._round(initial_value)
        self.text = self._format(self._last_valid)
        self.focused = False
        self._invalid_until = None

    def _round(self, value):
        return round(float(value), self.decimals) if self.decimals else int(value)

    def _format(self, value):
        return f"{value:.{self.decimals}f}" if self.decimals else str(value)

    def set_value(self, value):
        """Синхронизировать отображаемое значение без вызова on_confirm.
        Нужно, чтобы показать реальные стартовые значения (например
        config.pop_size), которые становятся известны только после того, как
        панель уже создана - см. UIPanel.sync_initial_values()."""
        self._last_valid = self._round(value)
        self.text = self._format(self._last_valid)
        self.focused = False
        self._invalid_until = None

    def _validate(self, text):
        if not text:
            return None
        try:
            value = float(text) if self.decimals else int(text)
        except ValueError:
            return None
        if self.min_value is not None and value < self.min_value:
            return None
        if self.max_value is not None and value > self.max_value:
            return None
        return self._round(value)

    def _confirm(self):
        value = self._validate(self.text)
        if value is None:
            self._invalid_until = time.time() + INVALID_FLASH_TIMEOUT
            self.text = self._format(self._last_valid)
            return
        self._last_valid = value
        self.text = self._format(value)
        if self.on_confirm:
            self.on_confirm(value)

    def handle_event(self, event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.focused = True
                return True
            else:
                if self.focused:
                    self._confirm()
                    self.focused = False
            return False
        if event.type == pygame.KEYDOWN and self.focused:
            if event.key == pygame.K_RETURN or event.key == pygame.K_KP_ENTER:
                self._confirm()
                self.focused = False
            elif event.key == pygame.K_ESCAPE:
                self.text = self._format(self._last_valid)
                self.focused = False
            elif event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.unicode and event.unicode.isdigit():
                if len(self.text) < 6:
                    self.text += event.unicode
            elif self.decimals and event.unicode == "." and "." not in self.text and self.text:
                if len(self.text) < 6:
                    self.text += event.unicode
            return True
        return False

    def draw(self, surface, font, label_font, offset=(0, 0)):
        rect = self.rect.move(-offset[0], -offset[1])
        lines = self.label.split("\n")
        line_h = label_font.get_height()
        label_top = rect.y - len(lines) * line_h - 4
        for i, line in enumerate(lines):
            surf = label_font.render(line, True, TEXT_MUTED)
            surface.blit(surf, (rect.x, label_top + i * line_h))

        if self._invalid_until is not None and time.time() < self._invalid_until:
            border_color = FIELD_BORDER_INVALID
        elif self.focused:
            border_color = FIELD_BORDER_FOCUS
        else:
            border_color = FIELD_BORDER
        pygame.draw.rect(surface, FIELD_BG, rect, border_radius=6)
        pygame.draw.rect(surface, border_color, rect, width=2, border_radius=6)
        text_surf = font.render(self.text, True, TEXT_COLOR)
        surface.blit(text_surf, (rect.x + 8, rect.centery - text_surf.get_height() // 2))


class UIPanel:
    """Панель управления и статистики - вертикальная колонка вдоль правого
    края окна.

    Владелец (Screen) создаёт панель один раз и переиспользует её между
    поколениями; eval_genomes на каждый кадр вызывает handle_event(...) для
    каждого pygame-события и draw(surface, stats) один раз за кадр, а после
    кадра забирает "одноразовые" запросы через consume_*().

    Layout строится сверху вниз при создании (см. _build_*) через курсор
    self._y - каждая секция сама продвигает его на свою высоту и добавляет
    SECTION_GAP перед собой; так порядок/состав секций можно менять, не
    пересчитывая координаты остальных вручную.
    """

    _STATS_LINE_COUNT = 14  # 13 строк статистики + 1 зарезервированная под PAUSED

    def __init__(self, field_width, field_height, panel_width=PANEL_WIDTH, initial_track="points.txt"):
        self.rect = pygame.Rect(field_width, 0, panel_width, field_height)

        self.title_font = pygame.font.SysFont('Arial', 20, bold=True)
        self.header_font = pygame.font.SysFont('Arial', 15, bold=True)
        self.font = pygame.font.SysFont('Arial', 16)
        self.small_font = pygame.font.SysFont('Arial', 13)

        self.paused = False
        self.unlimited_fps = False
        self.show_genome = True

        # Continuous-атрибуты (по аналогии с show_genome выше) - гейтят
        # отрисовку лучей-сенсоров машин и линий чекпоинтов (см. CLAUDE.md);
        # True по умолчанию = поведение до появления этих тоглов (и то, и
        # то рисовалось всегда безусловно).
        self.show_sensors = True
        self.show_track_lines = True

        # Камера игрового поля (см. car_racer/screen/camera.py) - `zoom`
        # читается neat_runner/main.py каждый кадр и присваивается
        # screen.camera.zoom напрямую (по аналогии с self.paused/
        # self.unlimited_fps выше - без consume_*, значение continuous, а не
        # одноразовое событие). `camera_follow` - включает центрирование
        # камеры на машине лучшего генома текущего поколения (best_env в
        # neat_runner/main.py) вместо показа всего трека целиком.
        self.zoom = DEFAULT_ZOOM
        self.camera_follow = False

        self._restart_group_requested = False
        self._restart_training_requested = False
        self._confirm_restart_armed_at = None
        self._track_changed_to = None
        self._max_visible_changed_to = None
        self._group_size_changed_to = None
        self._pop_size_changed_to = None
        self._fps_changed_to = None
        self._grip_changed_to = None
        self._mass_changed_to = None
        self._power_changed_to = None
        self._recompute_ideal_line_requested = False

        self.track_files = self._discover_tracks()
        if initial_track in self.track_files:
            self.track_index = self.track_files.index(initial_track)
        else:
            self.track_index = 0
        self.track_dropdown_open = False

        # -- построение layout'а --------------------------------------
        self._section_headers = []  # [(title, x, y)] - заголовки рисуются в draw()
        self._content_x = self.rect.x + PADDING
        self._content_w = self.rect.width - 2 * PADDING
        self._y = self.rect.y + PADDING

        self.buttons = []
        self.sliders = []
        self.text_fields = []

        self._build_title()
        self._build_stats_section()
        self._build_playback_section()
        self._build_track_section()
        self._build_camera_section()
        self._build_training_fields_section()
        self._build_vehicle_fields_section()

        # Скролл колесом мыши - см. handle_event/draw. Секции накопились за
        # сессию (Session Stats/Playback/Track/Camera/Training Params/
        # Vehicle) до того, что общая высота контента (self._y здесь, после
        # всех _build_*) стала больше self.rect.height (=field_height, экран
        # по вертикали) - нижние поля (Vehicle) обрезались/уезжали за нижний
        # край панели без возможности до них докликать. max_scroll - на
        # сколько px можно уйти вниз, чтобы последняя секция ровно совпала с
        # низом панели (0, если контент и так помещается - скролл неактивен).
        self.scroll_offset = 0
        self._content_bottom = self._y
        self.max_scroll = max(0, self._content_bottom - self.rect.bottom + PADDING)

    # -- дискавери файлов трасс ----------------------------------------
    def _discover_tracks(self):
        pattern = os.path.join(POINTS_DIR, "points*.txt")
        files = sorted(os.path.basename(p) for p in glob.glob(pattern))
        return files or ["points.txt"]

    # -- вспомогательные функции layout'а -------------------------------
    def _label_block_h(self):
        # Наши текстовые поля всегда используют 2-строчную подпись (см.
        # _build_training_fields_section/_build_vehicle_fields_section) - "+4"
        # соответствует отступу, который TextField.draw вычитает из rect.y.
        return self.small_font.get_height() * 2 + 4

    def _stats_row_h(self):
        return self.small_font.get_height() + 4

    def _add_section_header(self, title):
        self._section_headers.append((title, self._content_x, self._y))
        self._y += self.header_font.get_height() + HEADER_GAP

    def _add_field_row(self, entries):
        """entries: список (col_x, col_w, kwargs_для_TextField) - создаёт по
        одному TextField на элемент в ОДНОМ ряду и продвигает self._y на
        высоту подписи+поля этого ряда. Вызывающий сам добавляет
        FIELD_ROW_GAP перед следующим рядом, если он есть - как и с
        секциями, это позволяет легко переставлять/убирать ряды."""
        label_h = self._label_block_h()
        field_y = self._y + label_h
        fields = [TextField((col_x, field_y, col_w, FIELD_H), **kwargs) for col_x, col_w, kwargs in entries]
        self._y = field_y + FIELD_H
        return fields

    # -- построение секций -----------------------------------------------
    def _build_title(self):
        self._title_pos = (self._content_x, self._y)
        self._y += self.title_font.get_height() + 6
        self._title_divider_y = self._y

    def _build_stats_section(self):
        self._y += SECTION_GAP
        self._add_section_header("Session Stats")
        self._stats_y = self._y
        self._y += self._STATS_LINE_COUNT * self._stats_row_h()

    def _build_playback_section(self):
        self._y += SECTION_GAP
        self._add_section_header("Playback")
        x, w = self._content_x, self._content_w

        self.pause_button = Button((x, self._y, w, BUTTON_H), "Pause", on_click=self._on_pause_clicked,
                                    toggle=True, active_label="Resume")
        self._y += BUTTON_H + BUTTON_GAP

        self.restart_group_button = Button((x, self._y, w, BUTTON_H), "Restart Group",
                                            on_click=self._on_restart_group_clicked)
        self._y += BUTTON_H + BUTTON_GAP

        self.restart_training_button = Button((x, self._y, w, BUTTON_H), "Restart Training",
                                               on_click=self._on_restart_training_clicked)
        self._y += BUTTON_H + BUTTON_GAP

        self.fps_button = Button((x, self._y, w, BUTTON_H), "Unlimited FPS", on_click=self._on_fps_clicked,
                                  toggle=True, active_label="Unlimited FPS: ON")
        self._y += BUTTON_H + BUTTON_GAP

        # active=False (дефолт Button) - геном показан (как и было раньше),
        # кнопка предлагает "Hide Genome"; клик переключает на active=True -
        # геном скрыт, кнопка предлагает "Show Genome" обратно.
        self.show_genome_button = Button((x, self._y, w, BUTTON_H), "Hide Genome",
                                          on_click=self._on_show_genome_clicked,
                                          toggle=True, active_label="Show Genome")
        self._y += BUTTON_H + BUTTON_GAP

        # Тот же инвертированный паттерн, что у show_genome_button выше:
        # active=False - рисуется (дефолт, как было раньше, когда тоглов не
        # существовало вовсе), кнопка предлагает "Hide ..."; клик - скрыто,
        # кнопка предлагает "Show ..." обратно. Гейтят отрисовку лучей-
        # сенсоров машин (self.show_sensors, читается PhyCar/SimpleCar через
        # screen.show_sensors - см. CLAUDE.md) и линий чекпоинтов
        # (self.show_track_lines, читается Screen.draw_track) - расчёт
        # сенсоров/сама сетка чекпоинтов НЕ затрагиваются, только отрисовка.
        self.show_sensors_button = Button((x, self._y, w, BUTTON_H), "Hide Sensor Rays",
                                           on_click=self._on_show_sensors_clicked,
                                           toggle=True, active_label="Show Sensor Rays")
        self._y += BUTTON_H + BUTTON_GAP

        self.show_track_lines_button = Button((x, self._y, w, BUTTON_H), "Hide Track Lines",
                                                on_click=self._on_show_track_lines_clicked,
                                                toggle=True, active_label="Show Track Lines")
        self._y += BUTTON_H

        self.buttons += [self.pause_button, self.restart_group_button, self.restart_training_button,
                          self.fps_button, self.show_genome_button,
                          self.show_sensors_button, self.show_track_lines_button]

    def _build_track_section(self):
        self._y += SECTION_GAP
        self._add_section_header("Track")
        self.track_button = Button((self._content_x, self._y, self._content_w, BUTTON_H),
                                    self._track_label(), on_click=self._on_track_clicked, compact=True)
        self._y += BUTTON_H
        self.buttons.append(self.track_button)

    def _build_camera_section(self):
        self._y += SECTION_GAP
        self._add_section_header("Camera")
        x, w = self._content_x, self._content_w

        self.camera_follow_button = Button(
            (x, self._y, w, BUTTON_H), "Camera Follow", on_click=self._on_camera_follow_clicked,
            toggle=True, active_label="Camera Follow: ON")
        self._y += BUTTON_H + BUTTON_GAP

        self.zoom_slider = Slider(
            (x, self._y, w, BUTTON_H), "Zoom:", MIN_ZOOM, MAX_ZOOM, DEFAULT_ZOOM,
            on_change=self._on_zoom_changed, label_width=52, value_width=52)
        self._y += BUTTON_H + BUTTON_GAP

        # Пересчитывает идеальную траекторию (car_racer/trajectory/optimal_line.py)
        # текущей трассы с УЧЁТОМ текущих сцепления/массы/мощности машины
        # (см. vehicle_params_from_physic_car в том же модуле) - без этой
        # кнопки "идеальное" время круга оставалось бы посчитанным один раз
        # под старые/дефолтные характеристики, даже если их потом покрутили
        # в полях ниже. Занимает ~1с на сложных трассах - синхронный клик,
        # не автоматически на каждое изменение поля.
        self.recompute_ideal_line_button = Button(
            (x, self._y, w, BUTTON_H), "Recompute Ideal Line", on_click=self._on_recompute_ideal_line_clicked)
        self._y += BUTTON_H

        self.buttons += [self.camera_follow_button, self.recompute_ideal_line_button]
        self.sliders.append(self.zoom_slider)

    def _build_training_fields_section(self):
        # Значения по умолчанию здесь ставятся "на глаз" (совпадают с
        # дефолтами модульных переменных в neat_runner/main.py) и тут же
        # перезаписываются реальными через sync_initial_values() при первом
        # создании Screen - см. neat_runner/main.py::eval_genomes.
        #
        # pop_size - единственное поле с длинной 2-строчной подписью, поэтому
        # ему отведён отдельный полноширинный ряд, а не половина колонки, как
        # у остальных - иначе подпись налезала бы на соседнее поле.
        self._y += SECTION_GAP
        self._add_section_header("Training Params")
        col_w = (self._content_w - COLUMN_GAP) / 2
        col_x = [self._content_x, self._content_x + col_w + COLUMN_GAP]

        self.max_visible_field, self.group_size_field = self._add_field_row([
            (col_x[0], col_w, dict(label="Видимых машинок\n(1-30)", initial_value=10, min_value=1, max_value=30,
                                    on_confirm=self._on_max_visible_confirm)),
            (col_x[1], col_w, dict(label="Размер группы\n(1-300)", initial_value=30, min_value=1, max_value=300,
                                    on_confirm=self._on_group_size_confirm)),
        ])
        self._y += FIELD_ROW_GAP

        (self.pop_size_field,) = self._add_field_row([
            (self._content_x, self._content_w,
             dict(label="Pop size\n(после Restart Training)", initial_value=150, min_value=1, max_value=2000,
                  on_confirm=self._on_pop_size_confirm)),
        ])
        self._y += FIELD_ROW_GAP

        (self.fps_field,) = self._add_field_row([
            (self._content_x, self._content_w,
             dict(label="Render FPS\n(1-240)", initial_value=60, min_value=1, max_value=240,
                  on_confirm=self._on_fps_confirm)),
        ])

        self.text_fields += [self.max_visible_field, self.group_size_field, self.pop_size_field, self.fps_field]

    def _build_vehicle_fields_section(self):
        # Физика машины (car_racer/cars/physic_car.py) - выражены в
        # узнаваемых единицах для наглядности (g, кг, л.с.), а не в голых
        # игровых числах; см. комментарии у GRIP_ACCEL_PER_G/ENGINE_POWER_HP/
        # CAR_MASS в physic_car.py про то, что это условная (не физически
        # калиброванная) шкала. Применяются к НОВЫМ машинам следующей группы -
        # как MAX_VISIBLE/GROUP_SIZE, машины в процессе заезда не меняются.
        self._y += SECTION_GAP
        self._add_section_header("Vehicle")
        col_w = (self._content_w - COLUMN_GAP) / 2
        col_x = [self._content_x, self._content_x + col_w + COLUMN_GAP]

        self.grip_field, self.mass_field = self._add_field_row([
            (col_x[0], col_w, dict(label="Сцепление (g)\n(0.5-3.0)", initial_value=1.5, min_value=0.5,
                                    max_value=3.0, decimals=1, on_confirm=self._on_grip_confirm)),
            (col_x[1], col_w, dict(label="Вес (кг)\n(50-300)", initial_value=160, min_value=50, max_value=300,
                                    on_confirm=self._on_mass_confirm)),
        ])
        self._y += FIELD_ROW_GAP

        (self.power_field,) = self._add_field_row([
            (self._content_x, self._content_w, dict(label="Мощность (л.с.)\n(1-1000)", initial_value=15,
                                                      min_value=1, max_value=1000, on_confirm=self._on_power_confirm)),
        ])

        self.text_fields += [self.grip_field, self.mass_field, self.power_field]

    def _track_label(self):
        return f"Track: {self.track_files[self.track_index]}"

    # -- обработчики кликов -------------------------------------------
    def _on_pause_clicked(self):
        self.paused = self.pause_button.active

    def _on_fps_clicked(self):
        self.unlimited_fps = self.fps_button.active

    def _on_restart_group_clicked(self):
        self._restart_group_requested = True

    def _on_restart_training_clicked(self):
        now = time.time()
        if (self._confirm_restart_armed_at is not None
                and now - self._confirm_restart_armed_at <= CONFIRM_TIMEOUT):
            self._restart_training_requested = True
            self._confirm_restart_armed_at = None
            self.restart_training_button.label = "Restart Training"
        else:
            self._confirm_restart_armed_at = now
            self.restart_training_button.label = "Confirm? (click again)"

    def _on_track_clicked(self):
        if len(self.track_files) <= 1:
            return
        self.track_dropdown_open = not self.track_dropdown_open

    def _select_track(self, index):
        self.track_index = index
        self.track_button.label = self._track_label()
        self._track_changed_to = self.track_files[index]

    def _on_max_visible_confirm(self, value):
        self._max_visible_changed_to = value

    def _on_group_size_confirm(self, value):
        self._group_size_changed_to = value

    def _on_pop_size_confirm(self, value):
        self._pop_size_changed_to = value

    def _on_fps_confirm(self, value):
        self._fps_changed_to = value

    def _on_grip_confirm(self, value):
        self._grip_changed_to = value

    def _on_mass_confirm(self, value):
        self._mass_changed_to = value

    def _on_power_confirm(self, value):
        self._power_changed_to = value

    def _on_show_genome_clicked(self):
        self.show_genome = not self.show_genome_button.active

    def _on_show_sensors_clicked(self):
        self.show_sensors = not self.show_sensors_button.active

    def _on_show_track_lines_clicked(self):
        self.show_track_lines = not self.show_track_lines_button.active

    def _on_camera_follow_clicked(self):
        self.camera_follow = self.camera_follow_button.active

    def _on_zoom_changed(self, value):
        self.zoom = value

    def _on_recompute_ideal_line_clicked(self):
        self._recompute_ideal_line_requested = True

    # -- dropdown списка трасс ------------------------------------------
    def _track_dropdown_item_rects(self):
        # Список открывается ВНИЗ от кнопки - в отличие от старой нижней
        # панели, кнопка трассы больше не стоит у самого края окна, так что
        # открытие вниз спокойно помещается в оставшуюся высоту поля.
        # Рисуется на ГЛАВНОЙ (не скроллящейся) поверхности - якорим по
        # ТЕКУЩЕЙ видимой позиции кнопки (_scrolled_rect), а не по её
        # "дизайн"-координатам, иначе список отрывался бы от кнопки при
        # проскролленной панели.
        item_h = 30
        n = len(self.track_files)
        button_rect = self._scrolled_rect(self.track_button.rect)
        x = button_rect.x
        w = button_rect.width
        top = button_rect.bottom
        return [pygame.Rect(x, top + i * item_h, w, item_h) for i in range(n)]

    def _track_dropdown_hit(self, pos):
        for i, rect in enumerate(self._track_dropdown_item_rects()):
            if rect.collidepoint(pos):
                return i
        return None

    def _draw_track_dropdown(self, surface):
        # Рисуется на ГЛАВНОЙ поверхности (не на полупрозрачном panel_surf из
        # draw()) - полностью непрозрачным, чтобы список оставался читаемым,
        # даже вылезая за нижний край панели поверх игрового поля.
        for i, rect in enumerate(self._track_dropdown_item_rects()):
            color = BUTTON_ACTIVE_COLOR if i == self.track_index else BUTTON_COLOR
            pygame.draw.rect(surface, BUTTON_SHADOW, rect.move(0, 2), border_radius=4)
            pygame.draw.rect(surface, color, rect, border_radius=4)
            pygame.draw.rect(surface, BUTTON_BORDER, rect, width=1, border_radius=4)
            text_surf = self.small_font.render(self.track_files[i], True, BUTTON_TEXT_COLOR)
            surface.blit(text_surf, (rect.x + 10, rect.centery - text_surf.get_height() // 2))

    # -- публичный API для game loop -----------------------------------
    def set_paused(self, value: bool):
        self.paused = value
        self.pause_button.active = value

    def sync_initial_values(self, max_visible=None, group_size=None, pop_size=None, fps=None,
                            grip_g=None, mass_kg=None, power_hp=None,
                            zoom=None, camera_follow=None, show_genome=None, unlimited_fps=None,
                            show_sensors=None, show_track_lines=None):
        """Проставить реальные стартовые значения полей после того, как они
        стали известны (MAX_VISIBLE/GROUP_SIZE/FPS - модульные переменные
        neat_runner/main.py, pop_size - из neat.Config, grip_g/mass_kg/power_hp
        - из car_racer.cars.physic_car, остальное - из сохранённых настроек,
        см. car_racer/file_manager/settings_store.py) - панель создаётся
        раньше, чем eval_genomes получает cfg, поэтому конструктор не может
        знать их сразу. Не помечает значения как "изменённые пользователем"
        (никакого consume_*_change() после этого не сработает).

        zoom/camera_follow/show_genome/unlimited_fps/show_sensors/
        show_track_lines - continuous-атрибуты (не consume_*, читаются каждый
        кадр напрямую) - для них, в отличие от полей выше, нужно
        синхронизировать ещё и визуальное состояние кнопки/слайдера, иначе
        подпись кнопки ("Camera Follow" vs "Camera Follow: ON" и т.п.)
        разойдётся с реальным значением атрибута."""
        if max_visible is not None:
            self.max_visible_field.set_value(max_visible)
        if group_size is not None:
            self.group_size_field.set_value(group_size)
        if pop_size is not None:
            self.pop_size_field.set_value(pop_size)
        if fps is not None:
            self.fps_field.set_value(fps)
        if grip_g is not None:
            self.grip_field.set_value(grip_g)
        if mass_kg is not None:
            self.mass_field.set_value(mass_kg)
        if power_hp is not None:
            self.power_field.set_value(power_hp)
        if zoom is not None:
            self.zoom = zoom
            self.zoom_slider.set_value(zoom)
        if camera_follow is not None:
            self.camera_follow = camera_follow
            self.camera_follow_button.active = camera_follow
        if show_genome is not None:
            self.show_genome = show_genome
            self.show_genome_button.active = not show_genome
        if unlimited_fps is not None:
            self.unlimited_fps = unlimited_fps
            self.fps_button.active = unlimited_fps
        if show_sensors is not None:
            self.show_sensors = show_sensors
            self.show_sensors_button.active = not show_sensors
        if show_track_lines is not None:
            self.show_track_lines = show_track_lines
            self.show_track_lines_button.active = not show_track_lines

    def handle_event(self, event) -> bool:
        """Скармливать сюда каждое событие из pygame.event.get(). Возвращает
        True, если событие "поймано" панелью (клик пришёлся по кнопке/полю/
        пункту списка) - вызывающий код может использовать это, чтобы не
        путать клики по UI с кликами по игровому полю."""
        consumed = False

        if event.type == pygame.MOUSEWHEEL and self.max_scroll > 0:
            mouse_pos = pygame.mouse.get_pos()
            if self.rect.collidepoint(mouse_pos):
                # event.y > 0 - колесо "от себя" (вверх) - как в браузере/
                # большинстве интерфейсов, скроллит контент ВВЕРХ (offset
                # уменьшается, видно начало); знак минуса даёт это.
                self.scroll_offset = max(0, min(self.max_scroll, self.scroll_offset - event.y * SCROLL_STEP))
                return True

        if self.track_dropdown_open and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            item_index = self._track_dropdown_hit(event.pos)
            if item_index is not None:
                self._select_track(item_index)
                self.track_dropdown_open = False
                return True
            elif not self._scrolled_rect(self.track_button.rect).collidepoint(event.pos):
                # Клик мимо списка и мимо самой кнопки (в ТЕКУЩЕЙ, с учётом
                # скролла, позиции - см. _scrolled_rect) - закрыть список без
                # изменений, но НЕ поглощать событие: оно может быть кликом
                # по другой кнопке/полю, которые должны сработать как обычно.
                self.track_dropdown_open = False

        # Виджеты (buttons/sliders/fields) хранят rect в "дизайн"-координатах
        # - таких, как если бы скролла не было (см. _build_*_section выше) -
        # а видно/кликабельно их место сдвинуто на -scroll_offset (см. draw()
        # ниже). Поэтому здесь - обратный сдвиг: если панель проскроллена
        # вниз на N px, клик по видимой (сдвинутой вверх) кнопке нужно
        # сравнивать с её ИСХОДНЫМ (не сдвинутым) rect, т.е. считать, как
        # будто мышь была на N px НИЖЕ, чем реально кликнули.
        if self.scroll_offset and hasattr(event, "pos"):
            event = pygame.event.Event(event.type, dict(
                event.dict, pos=(event.pos[0], event.pos[1] + self.scroll_offset)))

        for field in self.text_fields:
            if field.handle_event(event):
                consumed = True

        for slider in self.sliders:
            if slider.handle_event(event):
                consumed = True

        for button in self.buttons:
            if button.handle_event(event):
                consumed = True

        return consumed

    def _scrolled_rect(self, rect):
        """rect (в "дизайн"-координатах, см. handle_event выше) в текущей,
        видимой на экране позиции с учётом scroll_offset."""
        return rect.move(0, -self.scroll_offset)

    def update(self):
        """Вызывать раз за кадр вне зависимости от событий - снимает
        "вооружённое" состояние подтверждения Restart Training по таймауту."""
        if (self._confirm_restart_armed_at is not None
                and time.time() - self._confirm_restart_armed_at > CONFIRM_TIMEOUT):
            self._confirm_restart_armed_at = None
            self.restart_training_button.label = "Restart Training"

    def consume_restart_group(self) -> bool:
        value, self._restart_group_requested = self._restart_group_requested, False
        return value

    def consume_restart_training(self) -> bool:
        value, self._restart_training_requested = self._restart_training_requested, False
        return value

    def consume_track_change(self):
        value, self._track_changed_to = self._track_changed_to, None
        return value

    def consume_max_visible_change(self):
        value, self._max_visible_changed_to = self._max_visible_changed_to, None
        return value

    def consume_group_size_change(self):
        value, self._group_size_changed_to = self._group_size_changed_to, None
        return value

    def consume_pop_size_change(self):
        value, self._pop_size_changed_to = self._pop_size_changed_to, None
        return value

    def consume_fps_change(self):
        value, self._fps_changed_to = self._fps_changed_to, None
        return value

    def consume_grip_change(self):
        value, self._grip_changed_to = self._grip_changed_to, None
        return value

    def consume_mass_change(self):
        value, self._mass_changed_to = self._mass_changed_to, None
        return value

    def consume_power_change(self):
        value, self._power_changed_to = self._power_changed_to, None
        return value

    def consume_recompute_ideal_line(self) -> bool:
        value, self._recompute_ideal_line_requested = self._recompute_ideal_line_requested, False
        return value

    # -- отрисовка ------------------------------------------------------
    def _draw_background(self, panel_surf):
        rect = panel_surf.get_rect()
        pygame.draw.rect(panel_surf, PANEL_BG, rect, border_top_left_radius=14, border_bottom_left_radius=14)
        pygame.draw.rect(panel_surf, PANEL_BORDER, rect, width=1,
                          border_top_left_radius=14, border_bottom_left_radius=14)

    def _draw_scrollbar(self, panel_surf):
        """Тонкая полоска-индикатор скролла у правого края панели - видна
        только когда контент реально не влезает (max_scroll > 0, см.
        __init__). Чисто индикатор, не перетаскиваемый мышью - скроллить
        можно только колесом (см. handle_event)."""
        track_h = self.rect.height - 2 * PADDING
        track_y = PADDING
        visible_frac = min(1.0, self.rect.height / self._content_bottom)
        thumb_h = max(24, int(track_h * visible_frac))
        scroll_frac = self.scroll_offset / self.max_scroll if self.max_scroll else 0.0
        thumb_y = track_y + int((track_h - thumb_h) * scroll_frac)
        thumb_rect = pygame.Rect(self.rect.width - PADDING // 2 - SCROLLBAR_WIDTH, thumb_y,
                                  SCROLLBAR_WIDTH, thumb_h)
        pygame.draw.rect(panel_surf, SCROLLBAR_COLOR, thumb_rect, border_radius=2)

    def _draw_title(self, panel_surf, offset):
        x, y = self._title_pos[0] - offset[0], self._title_pos[1] - offset[1]
        text_surf = self.title_font.render("Race Control", True, TITLE_COLOR)
        panel_surf.blit(text_surf, (x, y))
        divider_y = self._title_divider_y - offset[1]
        pygame.draw.line(panel_surf, TITLE_DIVIDER, (PADDING, divider_y),
                          (self.rect.width - PADDING, divider_y), 2)

    def _draw_section_header(self, panel_surf, title, x, y, offset):
        lx, ly = x - offset[0], y - offset[1]
        text_surf = self.header_font.render(title.upper(), True, HEADER_COLOR)
        panel_surf.blit(text_surf, (lx, ly))
        divider_y = ly + self.header_font.get_height() + 4
        pygame.draw.line(panel_surf, SECTION_DIVIDER, (lx, divider_y), (self.rect.width - PADDING, divider_y), 1)

    def _draw_stats(self, panel_surf, stats, offset):
        x = self._content_x - offset[0]
        y = self._stats_y - offset[1]
        row_h = self._stats_row_h()
        lines = [
            f"Generation: {stats.get('generation', '-')}",
            f"Genomes: {stats.get('genomes_range', '-')}",
            f"Left in group: {stats.get('left_in_group', '-')}",
            f"  ({stats.get('visible_count', 0)} vis / {stats.get('hidden_count', 0)} hid)",
            f"Time: {stats.get('time', 0):.2f} sec",
            f"FPS: {stats.get('fps', 0):.0f}",
            f"Best lap time: {stats.get('best_lap_time_str', '-')}",
            f"Max Distance: {stats.get('max_distance', 0) / PX_PER_METER:.1f} m",
            f"Best genome: {stats.get('best_genome_time_str', '-')}",
            f"Max CL: {stats.get('max_cl', 0)}",
            f"Max LAPS: {stats.get('max_laps', 0)}",
            f"Ideal lap: {stats.get('ideal_lap_time_str', '-')}",
            f"Max Fitness: {stats.get('max_fitness', 0):.2f}",
        ]
        for i, text in enumerate(lines):
            surf = self.small_font.render(text, True, TEXT_COLOR)
            panel_surf.blit(surf, (x, y + i * row_h))
        if self.paused:
            surf = self.small_font.render("PAUSED", True, PAUSED_COLOR)
            panel_surf.blit(surf, (x, y + len(lines) * row_h))

    def draw(self, surface, stats: dict):
        panel_surf = pygame.Surface(self.rect.size, pygame.SRCALPHA)
        # Фон/рамка панели - НЕ скроллится (рисуется по self.rect как есть,
        # т.е. offset=self.rect.topleft без scroll_offset); всё остальное
        # (заголовок/статистика/секции/виджеты) сдвигается на scroll_offset -
        # panel_surf сама по себе размером ровно с панель, поэтому контент,
        # уехавший за [0, rect.height), просто не рисуется (pygame сам
        # обрезает рисование за границами Surface) - отдельный clip-rect не
        # нужен.
        self._draw_background(panel_surf)

        offset = (self.rect.x, self.rect.y + self.scroll_offset)
        self._draw_title(panel_surf, offset)
        self._draw_stats(panel_surf, stats, offset)

        for title, x, y in self._section_headers:
            self._draw_section_header(panel_surf, title, x, y, offset)

        for button in self.buttons:
            button.draw(panel_surf, self.small_font if button.compact else self.font, offset=offset)

        for slider in self.sliders:
            slider.draw(panel_surf, self.font, self.small_font, offset=offset)

        for field in self.text_fields:
            field.draw(panel_surf, self.font, self.small_font, offset=offset)

        if self.max_scroll > 0:
            self._draw_scrollbar(panel_surf)

        surface.blit(panel_surf, self.rect.topleft)

        # См. docstring класса - вылезает за границы панели, поэтому рисуется
        # отдельно поверх основной поверхности, а не поверх panel_surf.
        if self.track_dropdown_open:
            self._draw_track_dropdown(surface)
