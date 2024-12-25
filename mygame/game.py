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
from mygame.constants import SCREEN_WIDTH, SCREEN_HEIGHT, NEURON_RADIUS, WHITE, BLACK, TIMEOUT, \
    FPS, GRIP, FORCE, DECELERATION, TRACK_COLOR, RED, CHECKPOINT_DIR, VIS_X, \
    VIS_Y, VIS_HEIGHT, VIS_WIDTH, CAR_WIDTH, CAR_HEIGHT

# Инициализация Pygame
pygame.init()

# Настройка окна
win = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Car Racing")

font = pygame.font.Font('freesansbold.ttf', 20)


def parse_track(filename):
    with open(filename, 'r') as file:
        lines = file.readlines()

        # Удаляем символы новой строки и пробелы
    lines = [line.strip() for line in lines if line.strip()]

    # Остальные строки
    other_lines = []
    for line in lines[2:]:
        # Преобразуем строку в список кортежей
        points = eval(line)
        tuple_points = (points[0], points[1])
        other_lines.append(tuple_points)

    return eval(lines[0]), eval(lines[1]), other_lines[:-1], other_lines[len(other_lines) - 1]


track_outer, track_inner, checkpoints_lines, start_line = parse_track("points.txt")


def print_x(w, coords):
    cross_length = 20

    pos_x, pos_y = coords
    # Координаты концов линий крестика
    left_top = (pos_x - cross_length, pos_y - cross_length)
    right_bottom = (pos_x + cross_length, pos_y + cross_length)
    right_top = (pos_x + cross_length, pos_y - cross_length)
    left_bottom = (pos_x - cross_length, pos_y + cross_length)

    # Рисование линий крестика
    pygame.draw.line(w, RED, left_top, right_bottom, 5)
    pygame.draw.line(w, RED, right_top, left_bottom, 5)


def print_text(w, text: str, coords):
    d_text = font.render(text, True, WHITE, BLACK)
    w.blit(d_text, coords)


def draw_network(win, genome, config):
    # Очистка области визуализации
    transparent_surface = pygame.Surface((VIS_WIDTH, VIS_HEIGHT), pygame.SRCALPHA)
    transparent_surface.fill((160, 160, 160, 190))  # Полупрозрачный белый фон

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
            pygame.draw.line(win, (0, 0, 255) if conn.weight < 0 else (255, 0, 0), start_pos, end_pos,
                             1 if conn.weight < 0 else 2)

    # Отображение нейронов
    for layer in layer_positions:
        for pos in layer:
            pygame.draw.circle(win, (0, 255, 0), pos, NEURON_RADIUS)

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
        genome.fitness = run_game_with_network(net, generation, genome, genome_id)
        print(f"Generation {generation}. Genome {genome_id} fitness: {genome.fitness:.2f}")
    save_checkpoint(p, generation)
    generation += 1
    print(f"Generation {generation} complete.")


max_fitness = 0
max_crossed_lines = 0

last_collistion = None


def out_of_screen(car):
    return car.x <= 0 or car.y <= 0


def run_game_with_network(network, generation_id, genome, genome_id):
    crossed_lines = 0
    already_crossed = []

    car = Car(130, 500)
    fitness = 0
    clock = pygame.time.Clock()
    running = True

    start_time = time.time()
    timeout = TIMEOUT
    while running:
        global max_fitness, max_crossed_lines
        max_fitness = max_fitness if max_fitness > fitness else fitness
        max_crossed_lines = max_crossed_lines if max_crossed_lines > crossed_lines else crossed_lines

        clock.tick(FPS)
        win.fill(BLACK)

        # Проверка на тайм-аут
        elapsed_time = timeout - (time.time() - start_time)
        if elapsed_time <= 0:
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
        if output[0] > 0.5:  # left
            car.angle -= 5 * (1 - GRIP * car.speed / car.mass)
        if output[0] < -0.5:  # right
            car.angle += 5 * (1 - GRIP * car.speed / car.mass)
        if output[1] > 0.5:  # throttle
            car.speed += FORCE / car.mass
        elif output[1] < -0.5:  # brake
            if (car.speed - FORCE / car.mass) > 0:
                car.speed -= FORCE / car.mass
        else:
            if car.speed > 0:
                car.speed -= DECELERATION / car.mass

        # Обновление машины
        car.update()

        pygame.draw.lines(win, TRACK_COLOR, True, track_outer, 3)
        pygame.draw.lines(win, TRACK_COLOR, True, track_inner, 3)

        for start_ch_line, end_ch_line in checkpoints_lines:
            pygame.draw.line(win, RED, start_ch_line, end_ch_line, 3)
        pygame.draw.line(win, (255, 255, 255), start_line[0], start_line[1], 5)

        print_text(win, f"Fitness: {fitness:.2f}", (10, 10))
        print_text(win, f"Time: {elapsed_time:.2f}", (10, 40))
        print_text(win, f"Crossed lines: {crossed_lines}", (10, 70))

        print_text(win, f"Genome: {genome_id}", (1050, 10))
        print_text(win, f"Generation: {generation_id}", (1050, 40))

        print_text(win, f"Max fitness: {max_fitness:.2f}", (1000, 740))
        print_text(win, f"Max CL: {max_crossed_lines}", (1000, 770))

        global last_collistion
        if last_collistion is not None:
            print_x(win, last_collistion)

        # Проверка столкновений
        car_rect = pygame.Rect(car.x - CAR_WIDTH // 2, car.y - CAR_WIDTH // 2, CAR_WIDTH // 2, CAR_WIDTH // 2)
        pygame.draw.rect(win, WHITE, car_rect, 4)

        if check_collision(car_rect, track_outer) or check_collision(car_rect, track_inner) or out_of_screen(car):
            print(f"Collision at position: ({car.x}, {car.y})")
            crossed_lines = 0
            running = False
            last_collistion = (car.x, car.y)
        if check_collision_by_line(car_rect, checkpoints_lines, already_crossed):
            print(f"Reached checkpoints: ({car.x}, {car.y})")
            crossed_lines += 1
            fitness += 1000 * crossed_lines
            timeout += 10
        if check_collision_by_line(car_rect, [start_line],
                                   already_crossed) and crossed_lines > 0 and crossed_lines % len(
            checkpoints_lines) == 0:
            print(f"Reached START LINE: ({car.x}, {car.y})")
            fitness += 5000 * len(crossed_lines)

        car.draw(win)

        # draw_network(win, genome, config)
        pygame.display.flip()
        # Увеличение фитнесс-функции за каждую пройденную дистанцию
        fitness += car.speed * 0.15

    return fitness


def get_inputs_for_network(car):
    # Пример: используем расстояния до ближайших препятствий как входы
    inputs = [car.angle, car.speed]

    for angle in [-150, -90, -45, 0, 45, 90, 150]:
        main_line = draw_line(car, angle)
        distance = float('inf')
        for line in [track_outer, track_inner]:
            for i in range(len(line) - 1):
                checked_line = LineString([line[i], line[i + 1]])
                intersection = main_line.intersection(checked_line)
                if not intersection.is_empty:
                    distance = min(distance, main_line.project(intersection))
                    pygame.draw.circle(win, WHITE, intersection.coords[0], 5)
        inputs.append(distance)

    return inputs


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
        # save_checkpoint(p, 'error')
        raise
