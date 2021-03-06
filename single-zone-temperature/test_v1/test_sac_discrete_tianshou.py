import os
import torch
import pprint
import argparse
import numpy as np
from torch.utils.tensorboard import SummaryWriter

from tianshou.policy import DQNPolicy
from tianshou.utils import BasicLogger
from tianshou.env import SubprocVectorEnv
from tianshou.trainer import offpolicy_trainer
from tianshou.data import Collector, VectorReplayBuffer
import torch.nn as nn
import gym_singlezone_temperature
import gym

from tianshou.utils.net.common import Net
from tianshou.policy import DiscreteSACPolicy
from tianshou.utils.net.discrete import Actor, Critic
import time

def get_args(folder):
    time_step = 15*60.0
    num_of_days = 7#31
    max_number_of_steps = int(num_of_days*24*60*60.0 / time_step)

    parser = argparse.ArgumentParser()
    parser.add_argument('--task', type=str, default="JModelicaCSSingleZoneTemperatureEnv-v1")
    parser.add_argument('--time-step', type=float, default=time_step)
    parser.add_argument('--seed', type=int, default=0)

    parser.add_argument('--eps-test', type=float, default=0.005)
    parser.add_argument('--eps-train', type=float, default=1.)
    parser.add_argument('--eps-train-final', type=float, default=0.05)
    
    parser.add_argument('--hidden-sizes', type=int, nargs='*', default=[256,256,256])

    parser.add_argument('--buffer-size', type=int, default=20000)
    parser.add_argument('--actor-lr', type=float, default=1e-4)
    parser.add_argument('--critic-lr', type=float, default=1e-3)
    parser.add_argument('--alpha-lr', type=float, default=3e-4)
    parser.add_argument('--gamma', type=float, default=0.99)
    parser.add_argument('--tau', type=float, default=0.005)
    parser.add_argument('--alpha', type=float, default=0.05)
    parser.add_argument('--auto-alpha', action="store_true", default=False)


    parser.add_argument('--n-step', type=int, default=1)

    parser.add_argument('--epoch', type=int, default=500)

    parser.add_argument('--step-per-epoch', type=int, default=max_number_of_steps)
    parser.add_argument('--step-per-collect', type=int, default=1)
    parser.add_argument('--update-per-step', type=float, default=1)
    parser.add_argument('--batch-size', type=int, default=128)

    parser.add_argument('--training-num', type=int, default=1)
    parser.add_argument('--test-num', type=int, default=1)

    parser.add_argument('--logdir', type=str, default='log_sac_dis')
    
    parser.add_argument('--device', type=str, default='cuda')
    parser.add_argument('--frames-stack', type=int, default=1)
    parser.add_argument('--resume-path', type=str, default=None)
    parser.add_argument('--watch', default=False, action='store_true',
                        help='watch the play of pre-trained policy only')
    parser.add_argument('--save-buffer-name', type=str, default=folder)

    parser.add_argument('--test-only', type=bool, default=False)

    parser.add_argument('--rew-norm', action="store_true", default=False)



    return parser.parse_args()


def make_building_env(args):
    weather_file_path = "./USA_CA_Riverside.Muni.AP.722869_TMY3.epw"
    mass_flow_nor = [0.75]
    npre_step = 3
    simulation_start_time = 212*24*3600.0
    simulation_end_time = simulation_start_time + args.step_per_epoch*args.time_step
    log_level = 7
    alpha = 1
    nActions = 37

    def rw_func(cost, penalty):
        if ( not hasattr(rw_func,'x')  ):
            rw_func.x = 0
            rw_func.y = 0

        #print(cost, penalty)
        #res = cost + penalty
        cost = cost[0]
        penalty = penalty[0]

        if rw_func.x > cost:
            rw_func.x = cost
        if rw_func.y > penalty:
            rw_func.y = penalty

        print("rw_func-cost-min=", rw_func.x, ". penalty-min=", rw_func.y)
        #res = penalty * 10.0
        #res = penalty * 300.0 + cost*1e4
        res = penalty * 500.0 + cost*5e4
        
        return res

    env = gym.make(args.task,
                   mass_flow_nor = mass_flow_nor,
                   weather_file = weather_file_path,
                   npre_step = npre_step,
                   simulation_start_time = simulation_start_time,
                   simulation_end_time = simulation_end_time,
                   time_step = args.time_step,
                   log_level = log_level,
                   alpha = alpha,
                   nActions = nActions,
                   rf = rw_func)
    return env
        
import time
import tqdm
import warnings
from collections import defaultdict
from typing import Dict, Union, Callable, Optional

from tianshou.data import Collector
from tianshou.policy import BasePolicy
from tianshou.trainer import test_episode, gather_info
from tianshou.utils import tqdm_config, MovAvg, BaseLogger, LazyLogger
def offpolicy_trainer_1(
    args: Dict,
    test_envs: SubprocVectorEnv,    
    policy: BasePolicy,
    train_collector: Collector,
    test_collector: Collector,
    max_epoch: int,
    step_per_epoch: int,
    step_per_collect: int,
    episode_per_test: int,
    batch_size: int,
    update_per_step: Union[int, float] = 1,
    train_fn: Optional[Callable[[int, int], None]] = None,
    test_fn: Optional[Callable[[int, Optional[int]], None]] = None,
    stop_fn: Optional[Callable[[float], bool]] = None,
    save_fn: Optional[Callable[[BasePolicy], None]] = None,
    save_checkpoint_fn: Optional[Callable[[int, int, int], None]] = None,
    resume_from_log: bool = False,
    reward_metric: Optional[Callable[[np.ndarray], np.ndarray]] = None,
    logger: BaseLogger = LazyLogger(),
    verbose: bool = True,
    test_in_train: bool = True,
) -> Dict[str, Union[float, str]]:

    if save_fn:
        warnings.warn("Please consider using save_checkpoint_fn instead of save_fn.")

    start_epoch, env_step, gradient_step = 0, 0, 0
    if resume_from_log:
        start_epoch, env_step, gradient_step = logger.restore_data()
    last_rew, last_len = 0.0, 0
    stat: Dict[str, MovAvg] = defaultdict(MovAvg)
    start_time = time.time()
    train_collector.reset_stat()
    test_collector.reset_stat()
    test_in_train = test_in_train and train_collector.policy == policy

    acts=[]
    obss=[]
    rews=[]
    for epoch in range(1 + start_epoch, 1 + max_epoch):
        # train
        policy.train()
        train_collector.reset_env()
        with tqdm.tqdm(
            total=step_per_epoch, desc=f"Epoch #{epoch}", **tqdm_config
        ) as t:
            while t.n < t.total:
                if train_fn:
                    train_fn(epoch, env_step)
                result = train_collector.collect(n_step=step_per_collect)
                if result["n/ep"] > 0 and reward_metric:
                    result["rews"] = reward_metric(result["rews"])
                env_step += int(result["n/st"])
                t.update(result["n/st"])
                logger.log_train_data(result, env_step)
                last_rew = result['rew'] if 'rew' in result else last_rew
                #print("last_rew:    ", train_collector.buffer)
                last_len = result['len'] if 'len' in result else last_len
                data = {
                    "env_step": str(env_step),
                    "rew": f"{last_rew:.2f}",
                    "len": str(int(last_len)),
                    "n/ep": str(int(result["n/ep"])),
                    "n/st": str(int(result["n/st"])),
                }
                if result["n/ep"] > 0:
                    if test_in_train and stop_fn and stop_fn(result["rew"]):
                        test_result = test_episode(
                            policy, test_collector, test_fn,
                            epoch, episode_per_test, logger, env_step)
                        if stop_fn(test_result["rew"]):
                            if save_fn:
                                save_fn(policy)
                            logger.save_data(
                                epoch, env_step, gradient_step, save_checkpoint_fn)
                            t.set_postfix(**data)
                            return gather_info(
                                start_time, train_collector, test_collector,
                                test_result["rew"], test_result["rew_std"])
                        else:
                            policy.train()
                for i in range(round(update_per_step * result["n/st"])):
                    gradient_step += 1
                    losses = policy.update(batch_size, train_collector.buffer)
                    for k in losses.keys():
                        stat[k].add(losses[k])
                        losses[k] = stat[k].get()
                        data[k] = f"{losses[k]:.3f}"
                    logger.log_update_data(losses, gradient_step)
                    t.set_postfix(**data)
            if t.n <= t.total:
                t.update()
        
        
        if save_fn:
            save_fn(policy)

        # watch for each episode to save data
        print("Setup test envs ...")
        policy.eval()
        test_envs.seed(args.seed)

        buffer = VectorReplayBuffer(args.step_per_epoch+1, len(test_envs))
        collector = Collector(policy, test_envs, buffer, exploration_noise=False)
        result = collector.collect(n_step=args.step_per_epoch)
        #buffer.save_hdf5(args.save_buffer_name)
        act=buffer._meta.__dict__['act']
        obs=buffer._meta.__dict__['obs']
        rew=buffer._meta.__dict__['rew']
        acts.append(act)
        obss.append(obs)
        rews.append(rew)
        #print(buffer._meta.__dict__.keys())
        rew = result["rews"].mean()
        print(f'Mean reward (over {result["n/ep"]} episodes): {rew}')

    np.save(args.save_buffer_name+'/his_act.npy', np.array(acts))
    np.save(args.save_buffer_name+'/his_obs.npy', np.array(obss))
    np.save(args.save_buffer_name+'/his_rew.npy', np.array(rews))

    return 1

def test_sac_discrete(args):
    tim_env = 0.0
    tim_ctl = 0.0
    tim_learn = 0.0
    
    env = make_building_env(args)

    args.state_shape = env.observation_space.shape or env.observation_space.n
    args.action_shape = env.action_space.shape or env.action_space.n
    
    print("Observations shape:", args.state_shape)
    print("Actions shape:", args.action_shape)


    # make environments
    train_envs = SubprocVectorEnv([lambda: make_building_env(args)
                                   for _ in range(args.training_num)])
    test_envs = SubprocVectorEnv([lambda: make_building_env(args)
                                  for _ in range(args.test_num)])
    # seed
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    train_envs.seed(args.seed)
    test_envs.seed(args.seed)


    # define model
    net = Net(args.state_shape, hidden_sizes=args.hidden_sizes, device=args.device)
    actor = Actor(net, args.action_shape, softmax_output=False, device=args.device).to(args.device)
    actor_optim = torch.optim.Adam(actor.parameters(), lr=args.actor_lr)

    net_c1 = Net(args.state_shape, hidden_sizes=args.hidden_sizes, device=args.device)
    critic1 = Critic(net_c1, last_size=args.action_shape, device=args.device).to(args.device)
    critic1_optim = torch.optim.Adam(critic1.parameters(), lr=args.critic_lr)
    net_c2 = Net(args.state_shape, hidden_sizes=args.hidden_sizes, device=args.device)
    critic2 = Critic(net_c2, last_size=args.action_shape, device=args.device).to(args.device)
    critic2_optim = torch.optim.Adam(critic2.parameters(), lr=args.critic_lr)

    if args.auto_alpha:
        target_entropy = 0.98 * np.log(np.prod(args.action_shape))
        log_alpha = torch.zeros(1, requires_grad=True, device=args.device)
        alpha_optim = torch.optim.Adam([log_alpha], lr=args.alpha_lr)
        args.alpha = (target_entropy, log_alpha, alpha_optim)

    # define policy
    policy = DiscreteSACPolicy(
        actor, actor_optim, critic1, critic1_optim, critic2, critic2_optim,
        args.tau, args.gamma, args.alpha, estimation_step=args.n_step,
        reward_normalization=args.rew_norm)
    
    
    # collector
    '''
    buffer = VectorReplayBuffer(
        args.buffer_size, buffer_num=len(train_envs), ignore_obs_next=True,
        save_only_last_obs=False, stack_num=args.frames_stack)
    '''
    train_collector = Collector(
        policy, train_envs,
        VectorReplayBuffer(args.buffer_size, len(train_envs)))
    test_collector = Collector(policy, test_envs)
    # train_collector.collect(n_step=args.buffer_size)
    # log
    log_path = os.path.join(args.logdir, args.task, 'discrete_sac')
    writer = SummaryWriter(log_path)
    writer.add_text("args", str(args))
    logger = BasicLogger(writer)

    buffer_test = VectorReplayBuffer(
        args.step_per_epoch+100, buffer_num=len(test_envs), ignore_obs_next=True,
        save_only_last_obs=False, stack_num=args.frames_stack)
    
    test_collector = Collector(policy, test_envs, buffer_test, exploration_noise=False)

    def save_fn(policy):
        torch.save(policy.state_dict(), os.path.join(log_path, 'policy.pth'))

    '''
    def stop_fn(mean_rewards):
        if env.spec.reward_threshold:
            return mean_rewards >= env.spec.reward_threshold
        else:
            return False
    '''

    
    # watch agent's performance
    def watch():
        print("Setup test envs ...")
        policy.eval()
        test_envs.seed(args.seed)

        print("Testing agent ...")
        buffer = VectorReplayBuffer(args.step_per_epoch+1, len(test_envs))
        '''
        VectorReplayBuffer(
                args.step_per_epoch+1, buffer_num=len(test_envs),
                ignore_obs_next=True, save_only_last_obs=False,
                stack_num=args.frames_stack)
        '''
        collector = Collector(policy, test_envs, buffer, exploration_noise=False)
        result = collector.collect(n_step=args.step_per_epoch)
        #buffer.save_hdf5(args.save_buffer_name)
        
        np.save(args.save_buffer_name+'/his_act_final.npy', buffer._meta.__dict__['act'])
        np.save(args.save_buffer_name+'/his_obs_final.npy', buffer._meta.__dict__['obs'])
        np.save(args.save_buffer_name+'/his_rew_final.npy', buffer._meta.__dict__['rew'])
        #print(buffer._meta.__dict__.keys())
        rew = result["rews"].mean()
        print(f'Mean reward (over {result["n/ep"]} episodes): {rew}')
    

    if not args.test_only:
        # test train_collector and start filling replay buffer
        train_collector.collect(n_step=args.batch_size * args.training_num)
        # trainer
        
        result = offpolicy_trainer_1(args = args, test_envs=test_envs,
            policy = policy, train_collector = train_collector, test_collector = test_collector, max_epoch = args.epoch,
            step_per_epoch = args.step_per_epoch, step_per_collect = args.step_per_collect, episode_per_test = args.test_num,
            batch_size = args.batch_size,
            #stop_fn=stop_fn, 
            save_fn=save_fn, logger=logger,
            update_per_step=args.update_per_step, test_in_train=False)
        '''

        result = offpolicy_trainer_1(
            policy = policy, train_collector = train_collector, test_collector = test_collector, max_epoch = 1,
            step_per_epoch = 100, step_per_collect = 1, episode_per_test = 1,
            batch_size = 64, train_fn=train_fn, test_fn=test_fn,
            #stop_fn=stop_fn, 
            save_fn=save_fn, logger=logger,
            update_per_step=args.update_per_step, test_in_train=False)
        '''
        #pprint.pprint(result)

        watch()
    

    
    if args.test_only:
        policy.load_state_dict(torch.load(args.resume_path, map_location=args.device))
        print("Loaded agent from: ", os.path.join(log_path, 'policy.pth'))
        watch()

if __name__ == '__main__':

    folder='./sac_results'
    if not os.path.exists(folder):
        os.mkdir(folder)

    start = time.time()
    print("Begin time {}".format(start))
    test_sac_discrete(get_args(folder))

    end = time.time()
    print("Total execution time {:.2f} seconds".format(end-start))
