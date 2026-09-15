"""Минимальная игровая панель: только две кнопки-тоггла — «показать сенсоры»
и «показать геном». Все остальные настройки/статистика вынесены в браузерную
панель (car_racer/dashboard), чтобы окно игры оставалось чистым (трасса + машины).

Оставлен тот же интерфейс, что ждёт Screen (конструктор UIPanel) и
neat_runner/main.py (panel.handle_event / panel.draw / panel.show_sensors /
panel.show_genome), но без слайдеров/полей/скролла/секций.
"""
import pygame

PANEL_WIDTH = 360

PADDING = 16
BUTTON_H = 32
BUTTON_GAP = 6

BUTTON_COLOR = (54, 58, 74, 230)
BUTTON_HOVER_COLOR = (78, 84, 108, 236)
BUTTON_ACTIVE_COLOR = (44, 138, 104, 240)
BUTTON_BORDER = (255, 255, 255, 34)
BUTTON_TEXT_COLOR = (240, 242, 248)
BUTTON_SHADOW = (0, 0, 0, 65)


class Button:
    """Простая кликабельная кнопка-прямоугольник с опциональным toggle-режимом.
    rect задаётся в координатах ПАНЕЛИ (относительно её левого верхнего угла)."""

    def __init__(self, rect, label, on_click=None, toggle=False, active_label=None):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.on_click = on_click
        self.toggle = toggle
        self.active = False
        self.active_label = active_label or label
        self.hovered = False

    def handle_event(self, event) -> bool:
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

    def draw(self, surface, font):
        rect = self.rect
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
        surface.blit(text_surf, text_surf.get_rect(center=rect.center))


class UIPanel:
    """Две кнопки-тоггла (сенсоры/геном), плавающие справа поверх игры без
    подложки: show_sensors (лучи сенсоров) и show_genome (визуализация сети)."""

    def __init__(self, field_width, field_height, panel_width=PANEL_WIDTH, initial_track="points.txt"):
        self.rect = pygame.Rect(field_width, 0, panel_width, field_height)
        self.font = pygame.font.SysFont('Arial', 16)

        self.show_sensors = True
        self.show_genome = False

        x = PADDING
        w = self.rect.width - 2 * PADDING
        y = PADDING
        btn_w = (w - BUTTON_GAP) // 2

        self.show_sensors_button = Button(
            (x, y, btn_w, BUTTON_H), "Hide Sensors",
            on_click=self._on_show_sensors_clicked, toggle=True, active_label="Show Sensors")

        self.show_genome_button = Button(
            (x + btn_w + BUTTON_GAP, y, btn_w, BUTTON_H), "Hide Genome",
            on_click=self._on_show_genome_clicked, toggle=True, active_label="Show Genome")

        self.buttons = [self.show_sensors_button, self.show_genome_button]

    def _on_show_sensors_clicked(self):
        self.show_sensors = not self.show_sensors_button.active

    def _on_show_genome_clicked(self):
        self.show_genome = not self.show_genome_button.active

    def set_initial(self, show_sensors=None, show_genome=None):
        """Проставить стартовые значения тогглов из сохранённых настроек
        (см. car_racer/file_manager/settings_store.py)."""
        if show_sensors is not None:
            self.show_sensors = bool(show_sensors)
            self.show_sensors_button.active = not self.show_sensors
        if show_genome is not None:
            self.show_genome = bool(show_genome)
            self.show_genome_button.active = not self.show_genome

    def handle_event(self, event) -> bool:
        """Событие приходит в логических координатах холста (см. main.py) -
        переводим в координаты панели перед проверкой кнопок."""
        if hasattr(event, "pos"):
            local_pos = (event.pos[0] - self.rect.x, event.pos[1] - self.rect.y)
            event = pygame.event.Event(event.type, dict(event.dict, pos=local_pos))
        for button in self.buttons:
            if button.handle_event(event):
                return True
        return False

    def draw(self, surface, stats=None):
        # Без подложки: кнопки рисуются на прозрачной поверхности и просто
        # болтаются поверх игрового поля.
        panel_surf = pygame.Surface(self.rect.size, pygame.SRCALPHA)
        for button in self.buttons:
            button.draw(panel_surf, self.font)
        surface.blit(panel_surf, self.rect.topleft)
