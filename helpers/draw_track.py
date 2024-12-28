import pygame
import sys

SCREEN_HEIGHT = 1200

SCREEN_WIDTH = 2000

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
BUTTON_COLOR = (100, 100, 200)
BUTTON_HOVER_COLOR = (150, 150, 250)


def save_points_to_file(points, filename="points.txt"):
    with open(filename, "w") as file:
        for point in points:
            points_string = "["
            for p in point:
                points_string += f"[{p[0]}, {p[1]}],"
            file.write(points_string[:-1])
            file.write("]\n")


def is_collinear(p1, p2, p3):
    # Проверка коллинеарности с использованием векторного произведения
    return (p2[0] - p1[0]) * (p3[1] - p1[1]) == (p3[0] - p1[0]) * (p2[1] - p1[1])


def simplify_path(points):
    if len(points) < 3:
        return points

    simplified = [points[0]]

    for i in range(1, len(points) - 1):
        if not is_collinear(simplified[-1], points[i], points[i + 1]):
            simplified.append(points[i])

    simplified.append(points[-1])
    return simplified


class Drawer:
    # Функция для сохранения точек в файл
    def __init__(self, scr):
        # Установка размеров окна
        self.screen = scr
        # Переменные для отслеживания состояния
        self.last_pos = None

        self.key_hold = False
        self.drawing = False
        self.is_button_hovered, self.is_save_button_hovered = False, False
        self.current_points = []
        self.step_points = []
        self.all_points = []
        self.font = pygame.font.Font(None, 20)

    def set_cursore_mode(self, value):
        self.last_pos = None
        self.cursor_mode = value

    # Функция для отрисовки кнопки
    def draw_button(self, position, text):
        pygame.draw.rect(self.screen, BUTTON_COLOR, (*position, 90, 30))

        text_surf = self.font.render(text, True, WHITE)
        self.screen.blit(text_surf, (position[0] + 10, position[1] + 10))

    def draw_by_curor(self, event):
        keys = pygame.key.get_pressed()
        if event.type == pygame.QUIT:
            save_points_to_file(self.all_points)
            pygame.quit()
            sys.exit()
        elif event.type == pygame.KEYUP:
            print("KEYUP")
            self.key_hold = False
        elif event.type == pygame.KEYDOWN:
            if not self.key_hold and keys[pygame.K_SPACE]:
                print("KEYDOWN")
                self.key_hold = True
                if len(self.current_points) > 0:
                    del self.current_points[-1]
        elif event.type == pygame.MOUSEBUTTONDOWN:
            print(self.current_points)
            if event.button == 1:  # Левая кнопка мыши
                self.step_points = []
                self.drawing = True
                self.last_pos = event.pos
                # if self.last_pos is not None:
                self.step_points.append(event.pos)
        elif event.type == pygame.MOUSEMOTION:
            if self.drawing:
                self.last_pos = event.pos
                self.step_points.append(event.pos)  # Добавляем новые точки
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:  # Левая кнопка мыши
                self.drawing = False
                self.current_points.append(simplify_path(self.step_points))  # Объединяем коллинеарные точки
                self.last_pos = event.pos

    def draw(self):
        mouse_pos = pygame.mouse.get_pos()

        self.add_bg_image()

        save_button_pos = (SCREEN_WIDTH - 100, 10)
        self.draw_button(save_button_pos, "Сохранить")
        is_save_button_clicked = (save_button_pos[0] <= mouse_pos[0] <= save_button_pos[0] + 100
                                  and save_button_pos[1] <= mouse_pos[1] <= save_button_pos[1] + 30)

        end_button_pos = (SCREEN_WIDTH - 100, 45)
        self.draw_button(end_button_pos, "Закончить")
        is_end_button_clicked = (end_button_pos[0] <= mouse_pos[0] <= end_button_pos[0] + 100
                                 and end_button_pos[1] <= mouse_pos[1] <= end_button_pos[1] + 30)

        all_crossed_points = [item for sublist in self.current_points for item in sublist]
        if len(all_crossed_points) > 1:
            pygame.draw.lines(screen, WHITE, False, all_crossed_points, 2)
        if len(self.step_points) > 1:
            pygame.draw.lines(screen, WHITE, False, self.step_points, 2)
        for lines in self.all_points:
            pygame.draw.lines(screen, WHITE, False, lines, 2)

        btn_click = is_save_button_clicked or is_end_button_clicked
        for event in pygame.event.get():
            if event.type == pygame.MOUSEBUTTONDOWN:
                if btn_click:
                    if is_save_button_clicked:
                        if len(self.current_points) > 0:
                            self.all_points.append([item for sublist in self.current_points for item in sublist])
                            self.current_points = []
                            self.step_points = []
                            self.last_pos = None
                    elif is_end_button_clicked:
                        save_points_to_file(self.all_points)
                        return True

                    return False

            self.draw_by_curor(event)

        return False

    def add_bg_image(self):
        imp = pygame.image.load("rb_ring.png").convert()
        imp = pygame.transform.scale(imp, (SCREEN_WIDTH, SCREEN_HEIGHT))

        # Using blit to copy content from one surface to other
        self.screen.blit(imp, (0, 0))


if __name__ == "__main__":
    # Инициализация Pygame
    pygame.init()

    # Установка размеров окна
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Рисование линий")

    drawer = Drawer(screen)
    ended = False
    while not ended:
        ended = drawer.draw()
        # Обновление экрана
        pygame.display.flip()

    pygame.quit()
