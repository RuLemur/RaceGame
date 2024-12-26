import os
import time

import neat
import pygame

from mygame.constants import SCREEN_WIDTH, SCREEN_HEIGHT, BLACK, FPS, CHECKPOINT_DIR, TRACK_COLOR, RED, WHITE, \
    GROUP_SIZE
from mygame.file_worker import save_checkpoint, load_checkpoint, parse_track
from mygame.game_instatnse import GameEnvironment

# Инициализация Pygame
pygame.init()

# Настройка окна
win = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Car Racing")

# def draw_network(win, genome, config):
#     # Очистка области визуализации
#     transparent_surface = pygame.Surface((VIS_WIDTH, VIS_HEIGHT), pygame.SRCALPHA)
#     transparent_surface.fill((160, 160, 160, 190))  # Полупрозрачный белый фон
#
#     # Получение информации о сети
#     net = neat.nn.FeedForwardNetwork.create(genome, config)
#
#     # Задайте координаты для слоев
#     layer_positions = []
#     input_nodes = config.genome_config.input_keys
#     output_nodes = config.genome_config.output_keys
#     hidden_nodes = list(set(genome.nodes.keys()) - set(input_nodes) - set(output_nodes))
#
#     # Вычисление позиций для каждого слоя
#     layer_positions.append(
#         [(VIS_X + 50, VIS_Y + VIS_HEIGHT // (len(input_nodes) + 1) * (i + 1)) for i in range(len(input_nodes))])
#     layer_positions.append([(VIS_X + VIS_WIDTH // 2, VIS_Y + VIS_HEIGHT // (len(hidden_nodes) + 1) * (i + 1)) for i in
#                             range(len(hidden_nodes))])
#     layer_positions.append([(VIS_X + VIS_WIDTH - 50, VIS_Y + VIS_HEIGHT // (len(output_nodes) + 1) * (i + 1)) for i in
#                             range(len(output_nodes))])
#
#     win.blit(transparent_surface, (VIS_X, VIS_Y))
#     # Отображение соединений
#     for conn_key, conn in genome.connections.items():
#         if conn.enabled:
#             in_node, out_node = conn_key
#             start_pos = layer_positions[0][input_nodes.index(in_node)] if in_node in input_nodes else \
#                 layer_positions[1][hidden_nodes.index(in_node)]
#             end_pos = layer_positions[2][output_nodes.index(out_node)] if out_node in output_nodes else \
#                 layer_positions[1][hidden_nodes.index(out_node)]
#             pygame.draw.line(win, (0, 0, 255) if conn.weight < 0 else (255, 0, 0), start_pos, end_pos,
#                              1 if conn.weight < 0 else 2)
#
#     # Отображение нейронов
#     for layer in layer_positions:
#         for pos in layer:
#             pygame.draw.circle(win, (0, 255, 0), pos, NEURON_RADIUS)
#
#     pygame.display.update()


# generation: int = 1
#
# max_fitness = 0
# max_crossed_lines = 0
#
# last_collistion = None


# def run_game_with_network(cfg, generation_id, genome, genome_id):
#     crossed_lines = 0
#     already_crossed = []
#
#     network = neat.nn.FeedForwardNetwork.create(genome, cfg)
#     start_x, start_y = get_midpoint(start_line)
#     car = Car(start_x, start_y)
#     fitness = 0
#     clock = pygame.time.Clock()
#     running = True
#
#     start_time = time.time()
#     timeout = TIMEOUT
#     while running:
#         global max_fitness, max_crossed_lines
#         max_fitness = max_fitness if max_fitness > fitness else fitness
#         max_crossed_lines = max_crossed_lines if max_crossed_lines > crossed_lines else crossed_lines
#
#         clock.tick(FPS)
#         win.fill(BLACK)
#
#         # Проверка на тайм-аут
#         elapsed_time = timeout - (time.time() - start_time)
#         if elapsed_time <= 0:
#             print(f"Timeout reached: {elapsed_time:.2f} seconds")
#             break
#
#         for event in pygame.event.get():
#             if event.type == pygame.QUIT:
#                 running = False
#             if event.type == pygame.MOUSEBUTTONDOWN:
#                 x, y = pygame.mouse.get_pos()
#                 print(x, y)
#
#         # Получение входных данных для нейросети
#         inputs = get_inputs_for_network(car)
#
#         # Получение выходных данных от нейросети
#         output = network.activate(inputs)
#
#         # Используем выходы сети для управления автомобилем
#         if output[0] > 0.5:  # left
#             car.angle -= 5 * (1 - GRIP * car.speed / car.mass)
#         if output[0] < -0.5:  # right
#             car.angle += 5 * (1 - GRIP * car.speed / car.mass)
#         if output[1] > 0.5:  # throttle
#             car.speed += FORCE / car.mass
#         elif output[1] < -0.5:  # brake
#             if (car.speed - FORCE / car.mass) > 0:
#                 car.speed -= FORCE / car.mass
#         else:
#             if car.speed > 0:
#                 car.speed -= DECELERATION / car.mass
#
#         # Обновление машины
#         car.update()
#
#         pygame.draw.lines(win, TRACK_COLOR, True, track_outer, 2)
#         pygame.draw.lines(win, TRACK_COLOR, True, track_inner, 2)
#
#         for start_ch_line, end_ch_line in checkpoints_lines:
#             pygame.draw.line(win, RED, start_ch_line, end_ch_line, 3)
#         pygame.draw.line(win, (255, 255, 255), start_line[0], start_line[1], 5)
#
#         print_text(win, f"Fitness: {fitness:.2f}", (10, 10))
#         print_text(win, f"Time: {elapsed_time:.2f}", (10, 40))
#         print_text(win, f"Crossed lines: {crossed_lines}", (10, 70))
#
#         print_text(win, f"Genome: {genome_id}", (1050, 10))
#         print_text(win, f"Generation: {generation_id}", (1050, 40))
#
#         print_text(win, f"Max fitness: {max_fitness:.2f}", (1000, 740))
#         print_text(win, f"Max CL: {max_crossed_lines}", (1000, 770))
#
#         global last_collistion
#         if last_collistion is not None:
#             print_x(win, last_collistion)
#
#         # Проверка столкновений
#         car_rect = pygame.Rect(car.x - CAR_WIDTH // 2, car.y - CAR_WIDTH // 2, CAR_WIDTH // 2, CAR_WIDTH // 2)
#         pygame.draw.rect(win, WHITE, car_rect, 4)
#
#         if check_collision(car_rect, track_outer) or check_collision(car_rect, track_inner) or out_of_screen(car):
#             print(f"Collision at position: ({car.x}, {car.y})")
#             crossed_lines = 0
#             running = False
#             last_collistion = (car.x, car.y)
#         if check_collision_by_line(car_rect, checkpoints_lines, already_crossed):
#             print(f"Reached checkpoints: ({car.x}, {car.y})")
#             crossed_lines += 1
#             fitness += 1000 * crossed_lines
#             timeout += 10
#         if check_collision_by_line(car_rect, [start_line],
#                                    already_crossed) and crossed_lines > 0 and crossed_lines % len(
#             checkpoints_lines) == 0:
#             print(f"Reached START LINE: ({car.x}, {car.y})")
#             fitness += 5000 * len(crossed_lines)
#
#         car.draw(win)
#
#         # draw_network(win, genome, config)
#         pygame.display.flip()
#         # Увеличение фитнесс-функции за каждую пройденную дистанцию
#         fitness += car.speed * 0.15
#
#     return fitness


generation = 0
max_fitness = 0
max_cl = 0


def eval_genomes(genomes, cfg):
    global generation, max_fitness, max_cl
    pygame.init()

    f = pygame.font.Font('freesansbold.ttf', 20)
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    clock = pygame.time.Clock()

    track_outer, track_inner, checkpoints_lines, start_line = parse_track("points.txt")

    # Разбейте геномы на группы
    num_groups = (len(genomes) + GROUP_SIZE - 1) // GROUP_SIZE  # Округление вверх

    # Для хранения всех сред для последующего отображения
    all_environments = []

    for group_index in range(num_groups):
        start_time = time.time()
        # Определите текущую группу
        start_index = group_index * GROUP_SIZE
        end_index = min(start_index + GROUP_SIZE - 1, len(genomes))
        current_group = genomes[start_index:end_index]

        # Создайте среду для текущей группы
        environments = [
            GameEnvironment(genome, cfg, genome_id, screen, track_outer, track_inner, checkpoints_lines, start_line) for
            genome_id, genome in current_group]
        all_environments.extend(environments)
        active_genomes = len(environments)
        # Основной цикл симуляции для текущей группы
        running = True
        while running and active_genomes > 0:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

            # Обновите и отрисуйте каждую среду
            screen.fill(BLACK)
            pygame.draw.lines(screen, TRACK_COLOR, True, track_outer, 2)
            pygame.draw.lines(screen, TRACK_COLOR, True, track_inner, 2)
            for start_ch_line, end_ch_line in checkpoints_lines:
                pygame.draw.line(screen, RED, start_ch_line, end_ch_line, 3)
            pygame.draw.line(screen, (255, 255, 255), start_line[0], start_line[1], 5)

            for env in environments:
                if env.active:
                    env.update()
                    env.render()
                    max_cl = env.get_cl() if env.get_cl() > max_cl else max_cl
                    max_fitness = env.get_fitness() if env.get_fitness() > max_fitness else max_fitness

                else:
                    active_genomes -= 1
            d_text = f.render(f"Generation: {generation}", True, WHITE, BLACK)
            screen.blit(d_text, (10, 10))
            d_text = f.render(f"Genoms: {start_index + 1}-{end_index + 1}", True, WHITE, BLACK)
            screen.blit(d_text, (10, 40))

            d_text = f.render(f"Max CL: {max_cl}", True, WHITE, BLACK)
            screen.blit(d_text, (840, 780))
            d_text = f.render(f"Max Fitness: {max_fitness:.2f}", True, WHITE, BLACK)
            screen.blit(d_text, (950, 780))

            d_text = f.render(f"Time: {time.time() - start_time:.2f} sec", True, WHITE, BLACK)
            screen.blit(d_text, (1030, 10))

            pygame.display.flip()
            clock.tick(FPS)

    pygame.quit()

    # Установите оценку для каждого генома
    for env, (genome_id, genome) in zip(all_environments, genomes):
        genome.fitness = env.get_fitness()

    save_checkpoint(p, generation)
    generation += 1
    print(f"Generation {generation} complete.")


if __name__ == "__main__":
    if not os.path.exists(CHECKPOINT_DIR):
        os.makedirs(CHECKPOINT_DIR)

    config_path = os.path.join(os.path.dirname(__file__), "config-feedforward.txt")
    config = neat.config.Config(neat.DefaultGenome, neat.DefaultReproduction,
                                neat.DefaultSpeciesSet, neat.DefaultStagnation,
                                config_path)

    # Пытаемся загрузить последнюю контрольную точку
    latest_checkpoint = None
    if os.path.exists(CHECKPOINT_DIR):
        checkpoints = [f for f in os.listdir(CHECKPOINT_DIR) if f.endswith('.pkl')]
        if checkpoints:
            latest_checkpoint = max(checkpoints, key=lambda f: int(f.split('-')[3].split('.')[0]))
            generation = int(latest_checkpoint.split('-')[3].split('.')[0])

    p = load_checkpoint(os.path.join(CHECKPOINT_DIR, latest_checkpoint)) if latest_checkpoint else neat.Population(
        config)

    # Добавление репортеров
    p.add_reporter(neat.StdOutReporter(True))
    stats = neat.StatisticsReporter()
    p.add_reporter(stats)

    # Запуск обучения
    try:
        winner = p.run(eval_genomes, 1000)
    except Exception as e:
        print(f"An error occurred: {e}")
        # save_checkpoint(p, 'error')
        raise
