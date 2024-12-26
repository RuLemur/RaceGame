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


generation = 1
max_fitness: int = 0
max_cl = 0
max_laps = 0


def eval_genomes(genomes, cfg):
    global generation, max_fitness, max_cl, max_laps
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
        end_index = min(start_index + GROUP_SIZE, len(genomes))
        current_group = genomes[start_index:end_index]

        # Создайте среду для текущей группы
        environments = [
            GameEnvironment(genome, cfg, genome_id, screen, track_outer, track_inner, checkpoints_lines, start_line) for
            genome_id, genome in current_group]

        all_environments.extend(environments)
        # Основной цикл симуляции для текущей группы
        running = True
        while running and any(env.active for env in environments):
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
                    max_laps = env.get_laps() if env.get_laps() > max_laps else max_laps

            d_text = f.render(f"Generation: {generation}", True, WHITE, BLACK)
            screen.blit(d_text, (10, 10))
            d_text = f.render(f"Genoms: {start_index + 1}-{end_index}", True, WHITE, BLACK)
            screen.blit(d_text, (10, 40))

            d_text = f.render(f"Max CL: {max_cl}", True, WHITE, BLACK)
            screen.blit(d_text, (830, 780))
            d_text = f.render(f"Max LAPS: {max_laps}", True, WHITE, BLACK)
            screen.blit(d_text, (680, 780))
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
