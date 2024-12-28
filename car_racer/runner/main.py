import pygame

from car_racer.cars.simplecar import SimpleCar
from car_racer.cars.physic_car import PhyCar
from car_racer.screen.screen import Screen
from helpers.calculate import get_midpoint

WIDTH, HEIGHT = 1200, 800


def run():
    window = Screen()
    clock = pygame.time.Clock()

    car_body = PhyCar(window, car_size=(35, 75))
    # car_body = SimpleCar(window, car_size=(35, 75))
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        window.draw_track()
        keys = pygame.key.get_pressed()

        if keys[pygame.K_UP]:
            car_body.throttle(1.0)
        elif keys[pygame.K_DOWN]:
            car_body.throttle(-1.0)
        else:
            car_body.damping(True, False)

        if keys[pygame.K_RIGHT]:
            car_body.turn(1.0)
        elif keys[pygame.K_LEFT]:
            car_body.turn(-1.0)
        else:
            car_body.damping(False, True)

        car_body.update()

        if car_body.check_collision_with_track():
            # running = False
            print("collision")
        # Отрисовка
        car_body.draw()

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()


if __name__ == '__main__':
    run()
