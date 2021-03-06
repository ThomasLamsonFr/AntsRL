import numpy as np
from numpy import ndarray
from typing import List, Optional
from utils import *

from environment.environment import Environment, EnvObject
from environment.pheromone import Pheromone
from environment.food import Food
from environment.ants import Ants
from environment.walls import Walls
from environment.circle_obstacles import CircleObstacles
from environment.anthill import Anthill
from environment.rewards.reward import Reward

DELTA = 1.1

class RLVisualization(EnvObject):
    def __init__(self, env: Environment, heatmap):
        super().__init__(env)
        self.heatmap = heatmap

class RLApi (EnvObject):
    def __init__(self, reward: Reward, reward_threshold: float, max_speed: float, max_rot_speed: float, carry_speed_reduction: float, backward_speed_reduction: float):
        """ Initializes an RL API. Call register_ants to register this API to a group of ants and its environment.
        :param max_speed: The maximum forward and backward speed at which ants can move.
        :param max_rot_speed: The maximum number of radians ants can turn at each step.
        :param carry_speed_reduction: How much one unit of carried food reduces the max speed (cumulative factor).
        :param backward_speed_reduction: How much moving backward reduces the max speed (factor).
        """
        super().__init__(None)
        self.reward = reward
        self.reward_threshold = reward_threshold

        self.ants = None
        self.original_ants_position = None

        self.perception_radius = 0
        self.perception_mask = None
        self.perceived_objects: List[EnvObject] = []
        self.perception_coords = None
        self.perception_fwd_delta = 0

        self.max_speed = max_speed
        self.max_rot_speed = max_rot_speed
        self.carry_speed_reduction = carry_speed_reduction
        self.backward_speed_reduction = backward_speed_reduction

        # If set to True, will save the perceptive field of each ant as an image to display over environment during visualization.
        self.save_perceptive_field = False
        self.perceptive_field = None


    def visualize_copy(self, newenv: Environment):
        return RLVisualization(newenv, self.reward.visualization())


    def register_ants(self, new_ants: Ants):
        if self.environment is not None:
            self.environment.detach_object(self)
        self.ants = new_ants
        self.environment = new_ants.environment
        self.environment.add_object(self)
        self.perceived_objects = []
        self.original_ants_position = new_ants.xy

        self.reward.setup(self.ants)

    #
    # def compute_ants_distance(self):
    # 	"""
    # 	Return the distance of the ant to the center of the anthill.
    # 	:return:
    # 	"""
    # 	center_anthill = []
    # 	for obj in self.environment.objects:
    # 		if isinstance(obj, Anthill):
    # 			center_anthill.append([obj.x, obj.y])
    # 	return np.linalg.norm(center_anthill - self.ants.xy)

    def setup_perception(self, radius: int, objects: List[EnvObject], mask=None, forward_delta=0):
        """Setups perception parameters for the group of ants.
        :param radius: Number of grid units the ant can see around itself.
        :param objects: List of environment objects the ant can perceive (= perception channels).
        :param mask: Square boolean matrix of side 2*radius+1, to mask certain grid units around the ant.
        :param forward_delta: How much should the perceptive field be shifted in front of the ant."""
        self.perception_radius = radius
        self.perception_mask = mask
        self.perceived_objects = objects
        self.perception_fwd_delta = forward_delta

        # Constructing relative grid coordinates of perceived slots in grid (2*radius+1, 2*radius+1, 2)
        self.perception_coords = np.dstack([np.arange(-radius, radius+1)[AX, :].repeat(2*radius+1, 0), np.arange(-radius, radius+1)[:, AX].repeat(2*radius+1, 1)]).astype(float)
        self.perception_coords *= DELTA


    def observation(self):
        """Performs an observation on the environment, by each individual ant, looking in front of itself.
        :return (n_ants, 2*radius+1, 2*radius+1, n_objects) numpy array, with -1 where the ant can't see because of the mask.
        :return (n_ants, 2 + n_phero) numpy array describing the state of the ant, with [mandibles' state, held food, pheromone activation 1, phero act 2...]."""
        xy_f = self.ants.xy.copy()
        t_f = self.ants.theta + np.pi * 0.5

        if self.perception_fwd_delta != 0:
            xy_f += np.array([np.cos(self.ants.theta), np.sin(self.ants.theta)]).T * self.perception_fwd_delta

        # Rotating the perception grid based on each individual ant's theta orientation
        cos_t = np.cos(t_f)
        sin_t = np.sin(t_f)
        relative_coords = self.perception_coords[AX, :, :].repeat(len(self.ants.ants), 0)
        relative_coords[:, :, :, 0], relative_coords[:, :, :, 1] = cos_t[:, AX, AX] * relative_coords[:, :, :, 0] - sin_t[:, AX, AX] * relative_coords[:, :, :, 1], \
                                                                   sin_t[:, AX, AX] * relative_coords[:, :, :, 0] + cos_t[:, AX, AX] * relative_coords[:, :, :, 1]

        # Adding individual ant's position to relative coordinates
        abs_coords = relative_coords + xy_f[:, AX, AX, :]

        # Rounding to integer grid coordinates and warping to other side of the map if too big/too small
        abs_coords = np.round(abs_coords).astype(int)
        abs_coords[:, :, :, 0] = np.mod(abs_coords[:, :, :, 0], self.environment.w)
        abs_coords[:, :, :, 1] = np.mod(abs_coords[:, :, :, 1], self.environment.h)


        perception = np.zeros(list(abs_coords.shape[:-1]) + [len(self.perceived_objects)])
        for i, obj in enumerate(self.perceived_objects):
            if isinstance(obj, Pheromone):
                perception[:, :, :, i] = obj.phero[abs_coords[:, :, :, 0], abs_coords[:, :, :, 1]] / obj.max_val
            elif isinstance(obj, Food):
                perception[:, :, :, i] = obj.qte[abs_coords[:, :, :, 0], abs_coords[:, :, :, 1]]
            elif isinstance(obj, Walls):
                perception[:, :, :, i] = obj.map[abs_coords[:, :, :, 0], abs_coords[:, :, :, 1]]
            elif isinstance(obj, Anthill):
                perception[:, :, :, i] = obj.area[abs_coords[:, :, :, 0], abs_coords[:, :, :, 1]]
            elif isinstance(obj, CircleObstacles):
                vecs = abs_coords[:, :, :, AX, :] - obj.centers[AX, AX, AX, :, :]
                dists = np.sum(vecs**2, axis=4)**0.5
                perception[:, :, :, i] = np.max(dists < obj.radiuses, axis=3)
            elif isinstance(obj, Ants):
                ants_xy = np.round(obj.xy.astype(int))
                ants_xy[:, 0] = np.mod(ants_xy[:, 0], self.environment.w)
                ants_xy[:, 1] = np.mod(ants_xy[:, 1], self.environment.h)
                ants_map = np.zeros((self.environment.w, self.environment.h), dtype=int)
                ants_map[ants_xy[:, 0], ants_xy[:, 1]] += 1
                perception[:, :, :, i] = ants_map[abs_coords[:, :, :, 0], abs_coords[:, :, :, 1]]

        if self.save_perceptive_field:
            self.perceptive_field = np.zeros((self.environment.w, self.environment.h), dtype=bool)

        if self.perception_mask is not None:
            perception = self.perception_mask[AX, :, :, AX] * (perception + 1) - 1

            if self.save_perceptive_field:
                self.perceptive_field[abs_coords[:, self.perception_mask, 0], abs_coords[:, self.perception_mask, 1]] = True
        elif self.save_perceptive_field:
            self.perceptive_field[abs_coords[:, :, :, 0], abs_coords[:, :, :, 1]] = True

        state = np.zeros((len(self.ants.ants), 2 + len(self.ants.pheromones)))
        state[:, 0] = self.ants.mandibles
        state[:, 1] = self.ants.holding
        state[:, 2:] = self.ants.phero_activation > 0

        agent_state = np.zeros((self.ants.n_ants, 2))
        agent_state[:, 0] = self.ants.holding
        agent_state[:, 1] = self.ants.seed

        self.reward.observation(abs_coords, perception, agent_state)
        return perception, agent_state, state


    def step(self, rotation: Optional[ndarray], on_off_pheromones: Optional[ndarray]):
        """ Applies the different ant actions to the ant group. A None action won't change the state of ants.
        :param rotation: How much the ant should turn right, will be multiplied by max_rot_speed
        :param open_close_mandibles: Are the mandibles opened or closed
        :param on_off_pheromones: Are the pheromones activated or not
        """
        open_close_mandibles = None
        #if open_close_mandibles is not None:
            #self.ants.update_mandibles(open_close_mandibles)

        xy = self.ants.prev_ants[:, 0:2].astype(int)
        open_close_mandibles = self.ants.mandibles.copy()
        for i, obj in enumerate(self.perceived_objects):
            if isinstance(obj, Food):
                open_close_mandibles = np.bitwise_or(obj.qte[xy[:, 0], xy[:, 1]] > 0, open_close_mandibles)
            elif isinstance(obj, Anthill):
                open_close_mandibles = np.bitwise_and(1 - obj.area[self.ants.x.astype(int), self.ants.y.astype(int)], open_close_mandibles)
        self.ants.update_mandibles(open_close_mandibles)

        if on_off_pheromones is not None:
            self.ants.activate_pheromone(on_off_pheromones)

        if rotation is not None:
            self.ants.rotate_ants(rotation * self.max_rot_speed)

        # Moves the ants forward
        fwd = np.ones(self.ants.n_ants) * self.max_speed * (1 - self.ants.holding * self.carry_speed_reduction)
        fwd[fwd < 0] *= self.backward_speed_reduction
        self.ants.forward_ants(fwd)

        perception, agent_state, state = self.observation()

        done = self.environment.max_time == self.environment.timestep

        reward = self.reward.step(done, rotation, open_close_mandibles, on_off_pheromones)
        self.ants.give_reward(reward - self.reward_threshold)
        return perception, agent_state, reward, done
