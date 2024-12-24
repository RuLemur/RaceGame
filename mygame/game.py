import signal
import sys

import pygame
import math
from shapely.geometry import LineString
import neat
import os
from shapely.geometry import LineString
import time
import pickle

from pygame import Surface
from shapely.geometry.base import BaseGeometry

from mygame.car import Car
from mygame.constants import SCREEN_WIDTH, SCREEN_HEIGHT, CAR_WIDTH, CAR_HEIGHT, NEURON_RADIUS, WHITE, BLACK, TIMEOUT, \
    FPS, GRIP, FORCE, DECELERATION, TRACK_COLOR, TRACK, TRACK2, CHECKPOINTS, START_LINE, RED, CHECKPOINT_DIR, VIS_X, \
    VIS_Y, VIS_HEIGHT, VIS_WIDTH

# Инициализация Pygame
pygame.init()

# Настройка окна
win = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Car Racing")


font = pygame.font.Font('freesansbold.ttf', 20)


def draw_network(win, genome, config):
    # Очистка области визуализации
    transparent_surface = pygame.Surface((VIS_WIDTH, VIS_HEIGHT), pygame.SRCALPHA)
    transparent_surface.fill((160, 160, 160, 128))  # Полупрозрачный белый фон

    # Получение информации о сети
    net = neat.nn.FeedForwardNetwork.create(genome, config)

    # Задайте координаты для слоев
    layer_positions = []
    input_nodes = config.genome_config.input_keys
    output_nodes = config.genome_config.output_keys
    hidden_nodes = list(set(genome.nodes.keys()) - set(input_nodes) - set(output_nodes))

    # Вычисление позиций для каждого слоя
    layer_positions.append(
        [(VIS_X + 50, VIS_Y + VIS_HEIGHT // (len(input_nodes) + 1) * (i + 1)) for i in range(len(input_nodes))])
    layer_positions.append([(VIS_X + VIS_WIDTH // 2, VIS_Y + VIS_HEIGHT // (len(hidden_nodes) + 1) * (i + 1)) for i in
                            range(len(hidden_nodes))])
    layer_positions.append([(VIS_X + VIS_WIDTH - 50, VIS_Y + VIS_HEIGHT // (len(output_nodes) + 1) * (i + 1)) for i in
                            range(len(output_nodes))])

    win.blit(transparent_surface, (VIS_X, VIS_Y))
    # Отображение соединений
    for conn_key, conn in genome.connections.items():
        if conn.enabled:
            in_node, out_node = conn_key
            start_pos = layer_positions[0][input_nodes.index(in_node)] if in_node in input_nodes else \
            layer_positions[1][hidden_nodes.index(in_node)]
            end_pos = layer_positions[2][output_nodes.index(out_node)] if out_node in output_nodes else \
            layer_positions[1][hidden_nodes.index(out_node)]
            pygame.draw.line(win, (0, 0, 0), start_pos, end_pos, 1 if conn.weight < 0 else 2)

    # Отображение нейронов
    for layer in layer_positions:
        for pos in layer:
            pygame.draw.circle(win, (0, 0, 255), pos, NEURON_RADIUS)


    pygame.display.update()


# Функция для вычисления конечной точки
def calculate_end_pos(start_pos, angle_degrees, length):
    angle_radians = math.radians(angle_degrees)
    end_x = start_pos[0] + length * math.cos(angle_radians)
    end_y = start_pos[1] - length * math.sin(angle_radians)  # Минус, потому что ось Y направлена вниз
    return int(end_x), int(end_y)


def check_collision(car_rect, track_lines):
    for i in range(len(track_lines) - 1):
        line_start = track_lines[i]
        line_end = track_lines[i + 1]
        if car_rect.clipline(line_start, line_end):
            return True
    return False


def check_collision_by_line(car_rect, track_lines, already_crossed):
    for line in track_lines:
        line_start, line_end = line
        if car_rect.clipline(line_start, line_end) and (line_start, line_end) not in already_crossed:
            already_crossed.append((line_start, line_end))
            return True
    return False


def draw_line(car, angle: int):
    car_position = (car.x, car.y)
    line_end_pos = calculate_end_pos(car_position, -car.angle + angle, 500)
    pygame.draw.line(win, WHITE, car_position, line_end_pos, 1)
    m_line = LineString([car_position, line_end_pos])
    return m_line


def draw_intersaction(m_line, inters, y_text_pos):
    if not inters.is_empty:
        # Вычисляем расстояние до точки пересечения от начала основной линии
        distance = m_line.project(inters)
        d_text = font.render(f"{distance:.2f}", True, WHITE, BLACK)
        win.blit(d_text, (10, y_text_pos))
        pygame.draw.circle(win, WHITE, inters.coords[0], 5)


generation: int = 1


def eval_genomes(genomes, config):
    global generation
    for genome_id, genome in genomes:
        net = neat.nn.FeedForwardNetwork.create(genome, config)
        genome.fitness = run_game_with_network(net, generation, genome_id)
        print(f"Generation {generation}. Genome {genome_id} fitness: {genome.fitness:.2f}")
    save_checkpoint(p, generation)
    generation += 1
    print(f"Generation {generation} complete.")


max_fitness = 0
max_crossed_lines = 0


def run_game_with_network(network, generation_id, genome_id):
    # Создание машины
    crossed_lines = 0
    already_crossed = []

    car = Car(130, 500)
    fitness = 0
    clock = pygame.time.Clock()
    running = True
    start_time = time.time()

    while running:
        global max_fitness, max_crossed_lines
        max_fitness = max_fitness if max_fitness > fitness else fitness
        max_crossed_lines = max_crossed_lines if max_crossed_lines > crossed_lines else crossed_lines

        fitness -= 0.001
        clock.tick(FPS)
        win.fill(BLACK)

        # Проверка на тайм-аут
        elapsed_time = time.time() - start_time
        if elapsed_time > TIMEOUT:
            print(f"Timeout reached: {elapsed_time:.2f} seconds")
            break

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.MOUSEBUTTONDOWN:
                x, y = pygame.mouse.get_pos()
                print(x, y)

        # Получение входных данных для нейросети
        inputs = get_inputs_for_network(car)

        # Получение выходных данных от нейросети
        output = network.activate(inputs)

        # Используем выходы сети для управления автомобилем
        if output[0] > 0.5:
            car.angle -= 5 * (1 - GRIP * car.speed / car.mass)
        if output[1] > 0.5:
            car.angle += 5 * (1 - GRIP * car.speed / car.mass)
        if output[2] > 0.5:
            car.speed += FORCE / car.mass
        elif output[3] > 0.5:
            car.speed -= FORCE / car.mass
        else:
            if car.speed > 0:
                car.speed -= DECELERATION / car.mass
            elif car.speed < 0:
                car.speed += DECELERATION / car.mass

        # Обновление машины
        car.update()

        pygame.draw.lines(win, TRACK_COLOR, True, TRACK, 3)
        pygame.draw.lines(win, TRACK_COLOR, True, TRACK2, 3)

        for start_ch_line, end_ch_line in CHECKPOINTS:
            pygame.draw.line(win, RED, start_ch_line, end_ch_line, 3)
        pygame.draw.line(win, (255, 255, 255), START_LINE[0], START_LINE[1], 5)

        d_text = font.render(f"{fitness:.2f}", True, WHITE, BLACK)
        win.blit(d_text, (10, 10))

        d_text = font.render(f"Max CL: {max_crossed_lines}", True, WHITE, BLACK)
        win.blit(d_text, (1000, 170))
        d_text = font.render(f"Max fitness: {max_fitness:.2f}", True, WHITE, BLACK)
        win.blit(d_text, (1000, 130))
        d_text = font.render(f"Crossed lines: {crossed_lines}", True, WHITE, BLACK)
        win.blit(d_text, (1000, 90))
        d_text = font.render(f"Generation: {generation_id}", True, WHITE, BLACK)
        win.blit(d_text, (1000, 50))
        d_text = font.render(f"Genome: {genome_id}", True, WHITE, BLACK)
        win.blit(d_text, (1000, 10))

        # Проверка столкновений
        car_rect = pygame.Rect(car.x - CAR_WIDTH // 2, car.y - CAR_HEIGHT // 2, CAR_WIDTH, CAR_HEIGHT)
        if check_collision(car_rect, TRACK) or check_collision(car_rect, TRACK2):
            print(f"Collision at position: ({car.x}, {car.y})")
            crossed_lines = 0
            fitness -= 100
            running = False
        if check_collision_by_line(car_rect, CHECKPOINTS, already_crossed):
            print(f"Reached checkpoints: ({car.x}, {car.y})")
            crossed_lines += 1
            fitness += 1000
        if check_collision_by_line(car_rect, [START_LINE],
                                   already_crossed) and crossed_lines > 0 and crossed_lines % len(CHECKPOINTS) == 0:
            print(f"Reached START LINE: ({car.x}, {car.y})")
            fitness += 5000

        car.draw(win)
        genome = list(p.population.values())[0]
        draw_network(win, genome, config)
        pygame.display.flip()
        # Увеличение фитнесс-функции за каждую пройденную дистанцию
        fitness += car.speed * 0.05


    return fitness


def get_inputs_for_network(car):
    # Пример: используем расстояния до ближайших препятствий как входы
    distances = []
    for angle in [0, 30, -30, 90, -90, 140, -140]:
        main_line = draw_line(car, angle)
        distance = float('inf')
        for line in [TRACK, TRACK2]:
            for i in range(len(line) - 1):
                checked_line = LineString([line[i], line[i + 1]])
                intersection = main_line.intersection(checked_line)
                if not intersection.is_empty:
                    distance = min(distance, main_line.project(intersection))
                    pygame.draw.circle(win, WHITE, intersection.coords[0], 5)
        distances.append(distance)

        distance = float('inf')
        for line in CHECKPOINTS:
            l_start, l_end = line
            checked_line = LineString([l_start, l_end])
            intersection = main_line.intersection(checked_line)
            if not intersection.is_empty:
                distance = min(distance, main_line.project(intersection))
                pygame.draw.circle(win, RED, intersection.coords[0], 5)

    return distances


def save_checkpoint(population, generation):
    filename = os.path.join(CHECKPOINT_DIR, f'neat-checkpoint-gen-{generation}.pkl')
    with open(filename, 'wb') as f:
        pickle.dump(population, f)
    print(f"Checkpoint saved to {filename}")


def load_checkpoint(filename):
    with open(filename, 'rb') as f:
        population = pickle.load(f)
    print(f"Checkpoint loaded from {filename}")
    return population


def signal_handler(sig, frame):
    print('Interrupt received, saving latest checkpoint...')
    save_checkpoint(p, str(generation))
    sys.exit(0)


if __name__ == "__main__":
    if not os.path.exists(CHECKPOINT_DIR):
        os.makedirs(CHECKPOINT_DIR)

    signal.signal(signal.SIGINT, signal_handler)

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
        save_checkpoint(p, 'error')
        raise
