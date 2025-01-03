import os
import pickle

import neat

CHECKPOINT_DIR = 'car_racer/checkpoints/checkpoints'
POINTS_DIR = 'car_racer/tracks/'
CONFIG_DIR = 'car_racer/config/'


def parse_track(filename):
    with open(POINTS_DIR + filename, 'r') as file:
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


def get_neat_config():
    config_path = os.path.join(CONFIG_DIR + "config-feedforward.txt")
    config = neat.config.Config(neat.DefaultGenome, neat.DefaultReproduction,
                                neat.DefaultSpeciesSet, neat.DefaultStagnation,
                                config_path)
    return config
