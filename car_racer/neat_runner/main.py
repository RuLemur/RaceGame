import os
import time

import neat
import pygame

from car_racer.constants import TIMEOUT, MAX_TIMEOUT
from car_racer.file_manager.file_worker import save_checkpoint, CHECKPOINT_DIR, load_checkpoint, get_neat_config
from car_racer.neat_runner.game_instatnse import GameEnvironment
from car_racer.screen.screen import Screen, SCREEN_WIDTH, SCREEN_HEIGHT

GROUP_SIZE = 1
FPS = 30

generation = 1
max_fitness: int = 0
max_cl = 0
max_laps = 0
best_lap_time = MAX_TIMEOUT


def eval_genomes(genomes, cfg):
    global generation, max_fitness, max_cl, max_laps, best_lap_time
    clock = pygame.time.Clock()

    screen = Screen()

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
            GameEnvironment(genome, cfg, genome_id, screen) for genome_id, genome in current_group]

        all_environments.extend(environments)
        # Основной цикл симуляции для текущей группы
        running = True
        while running and any(env.active for env in environments):
            left_in_group = sum(1 for env in environments if env.active)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
            screen.draw_track()
            for env in environments:
                if env.active:
                    env.update()
                    env.render()
                    max_cl = env.car.get_cl() if env.car.get_cl() > max_cl else max_cl
                    max_fitness = env.car.get_fitness() if env.car.get_fitness() > max_fitness else max_fitness
                    max_laps = env.car.get_laps() if env.car.get_laps() > max_laps else max_laps

                    lap_time = env.car.get_lap_time()
                    best_lap_time = lap_time if lap_time < best_lap_time and lap_time != 0 else best_lap_time
                screen.draw_all([(f"Generation: {generation}", (10, 10)),
                                 (f"Genoms: {start_index + 1}-{end_index}", (10, 40)),
                                 (f"Left in group: {left_in_group}", (10, 70)),
                                 (f"Best lap time: {best_lap_time:.2f}", (SCREEN_WIDTH - 200, SCREEN_HEIGHT - 130)),
                                 (f"Max CL: {max_cl}", (SCREEN_WIDTH - 200, SCREEN_HEIGHT - 100)),
                                 (f"Max LAPS: {max_laps}", (SCREEN_WIDTH - 200, SCREEN_HEIGHT - 70)),
                                 (f"Max Fitness: {max_fitness:.2f}", (SCREEN_WIDTH - 200, SCREEN_HEIGHT - 30)),
                                 (f"Time: {time.time() - start_time:.2f} sec", (SCREEN_WIDTH-200, 10)),
                                 ])

            pygame.display.flip()
            clock.tick(FPS)

    pygame.quit()

    # Установите оценку для каждого генома
    for env, (genome_id, genome) in zip(all_environments, genomes):
        genome.fitness = env.car.get_fitness()

    save_checkpoint(p, generation)
    generation += 1
    print(f"Generation {generation} complete.")


if __name__ == "__main__":
    if not os.path.exists(CHECKPOINT_DIR):
        os.makedirs(CHECKPOINT_DIR)

    config = get_neat_config()

    # Пытаемся загрузить последнюю контрольную точку
    latest_checkpoint = None
    if os.path.exists(CHECKPOINT_DIR):
        checkpoints = [f for f in os.listdir(CHECKPOINT_DIR) if f.endswith('.pkl')]
        if checkpoints:
            latest_checkpoint = max(checkpoints, key=lambda f: int(f.split('-')[3].split('.')[0]))
            generation = int(latest_checkpoint.split('-')[3].split('.')[0])

    p = load_checkpoint(os.path.join(CHECKPOINT_DIR, latest_checkpoint)) \
        if latest_checkpoint else neat.Population(config)

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
