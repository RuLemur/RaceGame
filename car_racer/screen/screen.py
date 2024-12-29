import pygame

from car_racer.file_manager.file_worker import parse_track

BLACK = (0, 0, 0)
RED = (255, 0, 0)
CHECKPOINT_COLOR = (15, 128, 0)
WHITE = (255, 255, 255)
GRAY = (104, 104, 104)
DARK_GRAY = (70, 70, 70)

TRACK_COLOR = (150, 150, 150)
SCREEN_WIDTH, SCREEN_HEIGHT = 2000, 1200

VIS_WIDTH, VIS_HEIGHT = 700, 350
VIS_X, VIS_Y = 20, 830
NEURON_RADIUS = 5


class Screen:
    def __init__(self, window_size=(SCREEN_WIDTH, SCREEN_HEIGHT)):
        pygame.init()
        self.font = pygame.font.Font(None, 25)

        # Настройка окна
        pygame.display.set_caption("Car Racing")
        self.screen_width, self.screen_height = window_size
        self.win = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.HWSURFACE | pygame.DOUBLEBUF)

        self.track_outer, self.track_inner, self.checkpoints_lines, self.start_line = parse_track("points.txt")

        self.texts: dict[str, tuple[str, tuple[int, int]]] = {}

    def get_window(self):
        return self.win

    def draw_track(self):
        self.win.fill(BLACK)
        pygame.draw.lines(self.win, TRACK_COLOR, True, self.track_outer, 2)
        pygame.draw.lines(self.win, TRACK_COLOR, True, self.track_inner, 2)
        for start_ch_line, end_ch_line in self.checkpoints_lines:
            pygame.draw.line(self.win, CHECKPOINT_COLOR, start_ch_line, end_ch_line, 3)
        pygame.draw.line(self.win, (255, 255, 255), self.start_line[0], self.start_line[1], 5)

    def get_track(self):
        return self.track_outer, self.track_inner

    def draw_all(self, values: [tuple[str, tuple[int, int]]]):
        for text, position in values:
            d_text = self.font.render(text, True, WHITE, BLACK)
            self.win.blit(d_text, position)

    def draw_network(self, genome, config):
        # Очистка области визуализации
        transparent_surface = pygame.Surface((VIS_WIDTH, VIS_HEIGHT), pygame.SRCALPHA)

        # Установите шрифт для отображения текста
        font =pygame.font.SysFont('Arial', 17, bold=False, italic=False)

        # Задайте координаты для слоев
        # layer_positions = []
        node_positions = {}
        input_nodes = config.genome_config.input_keys
        output_nodes = config.genome_config.output_keys
        hidden_nodes = list(set(genome.nodes.keys()) - set(input_nodes) - set(output_nodes))

        # Метки для входных и выходных нейронов
        input_labels = ["angle", "speed", "-150", "-90", "-45", "0", "45", "90", "150"]
        output_labels = ["throttle", "turn"]

        # Вычисление позиций для входного и выходного слоев
        input_positions = [(VIS_X + 50, VIS_Y + VIS_HEIGHT // (len(input_nodes) + 1) * (i + 1)) for i in
                           range(len(input_nodes))]
        output_positions = [(VIS_X + VIS_WIDTH - 50, VIS_Y + VIS_HEIGHT // (len(output_nodes) + 1) * (i + 1)) for i in
                            range(len(output_nodes))]
        #
        # layer_positions.append(input_positions)
        # layer_positions.append(output_positions)

        # Map input and output nodes to their positions
        for i, node in enumerate(input_nodes):
            node_positions[node] = input_positions[i]
        for i, node in enumerate(output_nodes):
            node_positions[node] = output_positions[i]

        # Проверка на наличие скрытых нейронов
        if hidden_nodes:
            # Создаем словарь для хранения уровней для каждого нейрона
            node_levels = {node: 0 for node in hidden_nodes}

            # Обновляем уровни на основе соединений
            for conn_key, conn in genome.connections.items():
                if conn.enabled:
                    in_node, out_node = conn_key
                    if in_node in hidden_nodes and out_node in hidden_nodes:
                        node_levels[out_node] = max(node_levels[out_node], node_levels[in_node] + 1)

            # Сортируем скрытые нейроны по уровню
            max_level = max(node_levels.values())
            hidden_layer_positions = []
            for level in range(max_level + 1):
                level_nodes = [node for node, lvl in node_levels.items() if lvl == level]
                positions = [(VIS_X + (VIS_WIDTH // (2 + max_level)) * (level + 1),
                              VIS_Y + VIS_HEIGHT // (len(level_nodes) + 1) * (i + 1)) for i in range(len(level_nodes))]
                hidden_layer_positions.append(positions)
                for i, node in enumerate(level_nodes):
                    node_positions[node] = positions[i]

            # layer_positions = [layer_positions[0]] + hidden_layer_positions + [layer_positions[1]]

        self.win.blit(transparent_surface, (VIS_X, VIS_Y))

        # Отображение соединений
        for conn_key, conn in genome.connections.items():
            if conn.enabled:
                in_node, out_node = conn_key
                start_pos = node_positions[in_node]
                end_pos = node_positions[out_node]
                pygame.draw.line(self.win, DARK_GRAY if conn.weight < 0 else GRAY, start_pos, end_pos, 1)

        # Отображение нейронов и меток
        for i, node in enumerate(input_nodes):
            pos = node_positions[node]
            pygame.draw.circle(self.win, (0, 255, 0), pos, NEURON_RADIUS)
            label_surface = font.render(input_labels[i], True, WHITE)
            self.win.blit(label_surface, (pos[0] - 60, pos[1] - 10))

        for i, node in enumerate(output_nodes):
            pos = node_positions[node]
            pygame.draw.circle(self.win, (0, 255, 0), pos, NEURON_RADIUS)
            label_surface = font.render(output_labels[i], True, WHITE)
            self.win.blit(label_surface, (pos[0] + 15, pos[1] - 10))

        # Отображение скрытых нейронов
        for node in hidden_nodes:
            pos = node_positions[node]
            pygame.draw.circle(self.win, (0, 255, 0), pos, NEURON_RADIUS)
