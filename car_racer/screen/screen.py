import pygame

from car_racer.file_manager.file_worker import parse_track

BLACK = (0, 0, 0)
RED = (255, 0, 0)
WHITE = (255, 255, 255)

TRACK_COLOR = (150, 150, 150)
SCREEN_WIDTH, SCREEN_HEIGHT = 1200, 800


class Screen:
    def __init__(self, window_size=(SCREEN_WIDTH, SCREEN_HEIGHT)):
        pygame.init()
        self.font = pygame.font.Font(None, 25)

        # Настройка окна
        pygame.display.set_caption("Car Racing")
        self.screen_width, self.screen_height = window_size
        self.win = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

        self.track_outer, self.track_inner, self.checkpoints_lines, self.start_line = parse_track("points.txt")

        self.texts: dict[str, tuple[str, tuple[int, int]]] = {}

    def get_window(self):
        return self.win

    def draw_track(self):
        self.win.fill(BLACK)
        pygame.draw.lines(self.win, TRACK_COLOR, True, self.track_outer, 2)
        pygame.draw.lines(self.win, TRACK_COLOR, True, self.track_inner, 2)
        for start_ch_line, end_ch_line in self.checkpoints_lines:
            pygame.draw.line(self.win, RED, start_ch_line, end_ch_line, 3)
        pygame.draw.line(self.win, (255, 255, 255), self.start_line[0], self.start_line[1], 5)

    def get_track(self):
        return self.track_outer, self.track_inner

    def draw_all(self, values: [tuple[str, tuple[int, int]]]):
        for text, position in values:
            d_text = self.font.render(text, True, WHITE, BLACK)
            self.win.blit(d_text, position)
