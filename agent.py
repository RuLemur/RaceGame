import pygame
import neat
import os

from game.game import run_game


# Ваша функция для оценки производительности генома
def eval_genomes(genomes, config):
    for genome_id, genome in genomes:
        net = neat.nn.FeedForwardNetwork.create(genome, config)
        genome.fitness = run_game_with_network(net)

# Ваша функция для запуска игры с данной нейронной сетью
def run_game_with_network(network):
    return run_game(network)

if __name__ == "__main__":
    # Загрузите конфигурацию
    config_path = os.path.join(os.path.dirname(__file__), "config-feedforward.txt")
    config = neat.config.Config(neat.DefaultGenome, neat.DefaultReproduction,
                                neat.DefaultSpeciesSet, neat.DefaultStagnation,
                                config_path)

    # Создайте популяцию
    p = neat.Population(config)

    # Добавьте репортеры для получения информации о процессе обучения
    p.add_reporter(neat.StdOutReporter(True))
    stats = neat.StatisticsReporter()
    p.add_reporter(stats)

    # Запустите обучение
    winner = p.run(eval_genomes, 50)
