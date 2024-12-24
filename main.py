import gymnasium

import rater_env

env = gymnasium.make('rater_env/RatWorld-v0', render_mode = "human")
env.reset()

episode_over = False
while not episode_over:
    action = env.action_space.sample()  # agent policy that uses the observation and info
    observation, reward, terminated, truncated, info = env.step(action)

    episode_over = terminated or truncated

print(env.reset())

