import pygame
import sys
if __name__ == "__main__":
    # Инициализация Pygame
    pygame.init()

    # Установка размеров окна
    screen = pygame.display.set_mode((1200, 800))
    pygame.display.set_caption("Рисование линий")

    # Переменные для отслеживания состояния
    last_pos = None
    points = []

    # Цвета
    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)
    BUTTON_COLOR = (100, 100, 200)
    BUTTON_HOVER_COLOR = (150, 150, 250)

    num_line = 0


    # Функция для сохранения точек в файл
    def save_points_to_file(points, filename="points.txt"):
        with open(filename, "w") as file:
            for point in points:
                points_string = "["
                for p in point:
                    points_string += f"[{p[0]}, {p[1]}],"
                file.write(points_string[:-1])
                file.write("]\n")


    # Функция для отрисовки кнопки
    def draw_button(screen, position, text, hovered):
        color = BUTTON_HOVER_COLOR if hovered else BUTTON_COLOR
        pygame.draw.rect(screen, color, (*position, 90, 30))
        font = pygame.font.Font(None, 20)
        text_surf = font.render(text, True, WHITE)
        screen.blit(text_surf, (position[0] + 10, position[1] + 10))


    def __init__():
        wPoints = []
        # Основной цикл программы
        while True:
            mouse_pos = pygame.mouse.get_pos()
            mouse_click = pygame.mouse.get_pressed()

            button_pos = (10, 10)
            is_button_hovered = button_pos[0] <= mouse_pos[0] <= button_pos[0] + 100 and button_pos[1] <= mouse_pos[
                1] <= \
                                button_pos[1] + 30

            save_button_pos = (1100, 10)
            is_save_button_hovered = save_button_pos[0] <= mouse_pos[0] <= save_button_pos[0] + 100 and save_button_pos[
                1] <= mouse_pos[1] <= \
                                     save_button_pos[1] + 30

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    save_points_to_file(points)
                    pygame.quit()
                    sys.exit()
                elif event.type == pygame.K_SPACE:
                    points.append(wPoints)
                    wPoints = []
                    last_pos = None
                    print("space")
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if is_button_hovered or is_save_button_hovered:
                        if is_button_hovered:
                            points.append(wPoints)
                            wPoints = []
                            last_pos = None
                            print("is_button_hovered")
                        if is_save_button_hovered:
                            save_points_to_file(points)
                            print("is_save_button_hovered")
                    # Если нажата кнопка мыши, проверяем, где именно
                    else:
                        wPoints.append(mouse_pos)
                        if last_pos is not None:
                            pygame.draw.line(screen, WHITE, last_pos, mouse_pos, 2)
                        else:
                            pygame.draw.circle(screen, WHITE, mouse_pos, 2)
                        last_pos = mouse_pos

            # Отрисовка кнопки "Сохранить"
            draw_button(screen, button_pos, "Закончить", is_button_hovered)
            draw_button(screen, save_button_pos, "Сохранить", is_save_button_hovered)

            # Обновление экрана
            pygame.display.flip()
