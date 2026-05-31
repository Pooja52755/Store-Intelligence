"""RL-based anomaly threshold tuning (Gymnasium + Stable-Baselines3)."""
import numpy as np
import logging
from typing import Optional

try:
    import gymnasium as gym
    from gymnasium import spaces
    from stable_baselines3 import PPO
except ImportError:
    gym = None
    PPO = None

logger = logging.getLogger(__name__)


class AnomalyThresholdEnv(gym.Env):
    """
    RL environment for learning optimal anomaly detection thresholds.
    
    State space (5D):
    - queue_depth_normalized: [0, 1]
    - conversion_rate: [0, 1]
    - hour_of_day_sin: [-1, 1]
    - hour_of_day_cos: [-1, 1]
    - visitor_count_normalized: [0, 1]
    
    Action space (discrete, 5 choices):
    - Queue spike threshold: [3, 4, 5, 6, 7] people
    
    Reward:
    - +1.0: Correctly predicted anomaly (queue spike led to conversion drop)
    - -0.5: False positive (queue spike but no conversion drop)
    - +0.1: Quiet period correctly identified as normal
    - -0.1: Missed anomaly (conversion dropped without queue warning)
    """
    
    def __init__(self, historical_events=None):
        """
        Initialize environment.
        
        Args:
            historical_events: List of historical event dicts with keys:
                - queue_depth: int
                - conversion_rate: float [0, 1]
                - hour: int [0, 23]
                - visitor_count: int
        """
        super().__init__()
        
        self.observation_space = spaces.Box(
            low=0,
            high=1,
            shape=(5,),
            dtype=np.float32
        )
        
        self.action_space = spaces.Discrete(5)
        self.thresholds = [3, 4, 5, 6, 7]
        
        # Mock historical events if none provided
        if historical_events is None:
            historical_events = self._generate_mock_events(1000)
        
        self.historical_events = historical_events
        self.current_step = 0
        self.max_steps = min(len(historical_events) - 1, 500)
    
    def step(self, action):
        """
        Execute one step of environment.
        
        Args:
            action: Discrete action (0-4) selecting threshold
        
        Returns:
            (obs, reward, done, truncated, info)
        """
        if self.current_step >= self.max_steps:
            obs = self._get_obs()
            return obs, 0, True, False, {}
        
        threshold = self.thresholds[action]
        
        # Compute reward based on current and next events
        reward = self._compute_reward(threshold)
        
        self.current_step += 1
        obs = self._get_obs()
        done = self.current_step >= self.max_steps
        
        return obs, reward, done, False, {}
    
    def reset(self, seed=None):
        """Reset environment."""
        super().reset(seed=seed)
        self.current_step = 0
        return self._get_obs(), {}
    
    def _get_obs(self):
        """Get current observation."""
        if self.current_step >= len(self.historical_events):
            # Return zeros if beyond history
            return np.zeros(5, dtype=np.float32)
        
        event = self.historical_events[self.current_step]
        
        return np.array([
            min(event['queue_depth'] / 10.0, 1.0),  # Normalize to [0, 1]
            event['conversion_rate'],
            np.sin(2 * np.pi * event['hour'] / 24),  # Hour sine
            np.cos(2 * np.pi * event['hour'] / 24),  # Hour cosine
            min(event['visitor_count'] / 100.0, 1.0),  # Normalize to [0, 1]
        ], dtype=np.float32)
    
    def _compute_reward(self, threshold: int) -> float:
        """
        Compute reward for this threshold choice.
        
        Args:
            threshold: Queue depth threshold to test
        
        Returns:
            Reward value
        """
        current_event = self.historical_events[self.current_step]
        next_event = self.historical_events[
            min(self.current_step + 1, len(self.historical_events) - 1)
        ]
        
        queue_spiked = current_event['queue_depth'] > threshold
        conversion_dropped = (
            next_event['conversion_rate'] < (current_event['conversion_rate'] * 0.7)
        )
        
        if queue_spiked and conversion_dropped:
            # Correct anomaly prediction
            return 1.0
        elif queue_spiked and not conversion_dropped:
            # False positive
            return -0.5
        elif not queue_spiked and not conversion_dropped:
            # Correctly identified as normal
            return 0.1
        else:
            # Missed anomaly
            return -0.1
    
    @staticmethod
    def _generate_mock_events(count: int) -> list:
        """Generate mock historical events for testing."""
        import random
        events = []
        for i in range(count):
            hour = (i * 24 // count) % 24
            base_queue = max(0, 2 + np.sin(2 * np.pi * hour / 24) * 3)
            base_conversion = 0.3 + np.sin(2 * np.pi * hour / 24) * 0.1
            
            events.append({
                'queue_depth': int(base_queue + random.gauss(0, 1)),
                'conversion_rate': max(0, min(1, base_conversion + random.gauss(0, 0.05))),
                'hour': hour,
                'visitor_count': int(50 + np.sin(2 * np.pi * hour / 24) * 30 + random.gauss(0, 5)),
            })
        return events


class RLThresholdTuner:
    """Train and use RL policy for threshold tuning."""
    
    def __init__(self, model_path: str = "./models/rl_threshold_policy"):
        """
        Initialize tuner.
        
        Args:
            model_path: Path to save/load trained model
        """
        self.model_path = model_path
        self.model = None
        self.default_threshold = 5
        
        # Startup log
        logger.info("=== RL THRESHOLD TUNER STARTUP ===")
        logger.info("RL model path: %s", self.model_path)
        logger.info("Default threshold: %d", self.default_threshold)
        logger.info("Threshold options: [3, 4, 5, 6, 7]")
        logger.info("====================================")
    
    def train(self, historical_events=None, timesteps: int = 10000):
        """
        Train RL policy offline.
        
        Args:
            historical_events: List of historical event dicts
            timesteps: Number of training timesteps
        
        Returns:
            True if training successful, False otherwise
        """
        if gym is None or PPO is None:
            logger.warning("Gymnasium or SB3 not available, using default threshold")
            return False
        
        try:
            env = AnomalyThresholdEnv(historical_events)
            
            self.model = PPO(
                "MlpPolicy",
                env,
                verbose=0,
                learning_rate=3e-4,
                n_steps=128,
                batch_size=32,
                n_epochs=20
            )
            
            logger.info(f"Training RL policy for {timesteps} timesteps")
            self.model.learn(total_timesteps=timesteps)
            
            # Save model
            import os
            os.makedirs(os.path.dirname(self.model_path) or ".", exist_ok=True)
            self.model.save(self.model_path)
            logger.info(f"Saved trained policy to {self.model_path}")
            
            return True
        
        except Exception as e:
            logger.error(f"Training failed: {e}")
            return False
    
    def load(self):
        """Load trained model."""
        if PPO is None:
            logger.warning("Gymnasium or SB3 not available")
            return False
        
        try:
            self.model = PPO.load(self.model_path)
            logger.info(f"Loaded policy from {self.model_path}")
            return True
        except Exception as e:
            logger.warning(f"Could not load policy: {e}")
            return False
    
    def get_optimal_threshold(
        self,
        queue_depth: int,
        conversion_rate: float,
        hour: int,
        visitor_count: int
    ) -> int:
        """
        Get optimal threshold using trained policy or default.
        
        Args:
            queue_depth: Current queue depth
            conversion_rate: Current conversion rate
            hour: Current hour of day
            visitor_count: Current visitor count
        
        Returns:
            Optimal threshold (3-7)
        """
        if self.model is None:
            logger.info("RL FALLBACK MODE ACTIVE - using default threshold: %d", self.default_threshold)
            return self.default_threshold
        
        try:
            # Build observation
            obs = np.array([
                min(queue_depth / 10.0, 1.0),
                max(0, min(1, conversion_rate)),
                np.sin(2 * np.pi * hour / 24),
                np.cos(2 * np.pi * hour / 24),
                min(visitor_count / 100.0, 1.0),
            ], dtype=np.float32)
            
            action, _ = self.model.predict(obs, deterministic=True)
            threshold = [3, 4, 5, 6, 7][action]
            
            # Log RL decision
            logger.info(
                "RL DECISION: threshold adjusted from %d -> %d (queue_depth=%d, conversion_rate=%.2f, hour=%d, visitor_count=%d)",
                self.default_threshold,
                threshold,
                queue_depth,
                conversion_rate,
                hour,
                visitor_count
            )
            
            return threshold
        
        except Exception as e:
            logger.warning(f"Policy prediction failed: {e}")
            logger.info("RL FALLBACK MODE ACTIVE - using default threshold: %d", self.default_threshold)
            return self.default_threshold


# Global instance
rl_tuner = RLThresholdTuner()
