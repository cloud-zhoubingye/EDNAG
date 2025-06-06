import torch
from utils.corrector import normalize

def ddim_step(xt, x0, alphas: tuple, noise: float = None):
    """One step of the DDIM algorithm.

    Args:
    - xt: torch.Tensor, shape (n, d), the current samples.
    - x0: torch.Tensor, shape (n, d), the estimated origin.
    - alphas: tuple of two floats, alpha_{t} and alpha_{t-1}.

    Returns:
    - x_next: torch.Tensor, shape (n, d), the next samples.
    """
    alphat, alphatp = alphas
    # 计算噪声强度sigma
    sigma = ddpm_sigma(alphat, alphatp) * noise
    # 执行一步DDIM的反向去噪迭代
    eps = (xt - (alphat ** 0.5) * x0) / (1.0 - alphat) ** 0.5
    if sigma is None:
        sigma = ddpm_sigma(alphat, alphatp)
    x_next = (alphatp ** 0.5) * x0 + ((1 - alphatp - sigma ** 2) ** 0.5) * eps + sigma * torch.randn_like(x0)
    return x_next


def ddpm_sigma(alphat, alphatp):
    """Compute the default sigma for the DDPM algorithm."""
    return ((1 - alphatp) / (1 - alphat) * (1 - alphat / alphatp)) ** 0.5


class BayesianEstimator:
    """Bayesian Estimator of the origin points, based on current samples and fitness values."""
    def __init__(self, x: torch.tensor, fitness: torch.tensor, alpha, density='uniform', h=0.1):
        self.x = x
        self.fitness = fitness
        self.alpha = alpha
        self.density_method = density
        self.h = h
        if not density in ['uniform']:
            raise NotImplementedError(f'Density estimator {density} is not implemented.')

    def append(self, estimator):
        # 将另一个估计器的样本数据和适应度值拼接到当前估计器中
        self.x = torch.cat([self.x, estimator.x], dim=0)
        self.fitness = torch.cat([self.fitness, estimator.fitness], dim=0)
    
    def density(self, x):
        # 根据不同的概率分布，计算概率密度值
        if self.density_method == 'uniform':
            return torch.ones(x.shape[0]) / x.shape[0]
    
    @staticmethod
    def norm(x):
        # 计算向量的范数
        if x.shape[-1] == 1:
            # for some reason, torch.norm become very slow when dim=1, so we use torch.abs instead
            return torch.abs(x).squeeze(-1)
        else:
            return torch.norm(x, dim=-1)

    def gaussian_prob(self, x, mu, sigma):
        # 计算高斯分布的概率密度值
        dist = self.norm(x - mu)
        return torch.exp(-(dist ** 2) / (2 * sigma ** 2))

    def _estimate(self, x_t, p_x_t):
        # diffusion proability, P = N(x_t; \sqrt{α_t}x,\sqrt{1-α_t})
        mu = self.x * (self.alpha ** 0.5)   # 均值
        sigma = (1 - self.alpha) ** 0.5     # 标准差
        p_diffusion = self.gaussian_prob(x_t, mu, sigma)
        # 通过概率和适应度值估计原始样本（+1e-9是为了防止为0出错）
        prob = (self.fitness + 1e-9) * (p_diffusion + 1e-9) / (p_x_t + 1e-9)
        z = torch.sum(prob)
        origin = torch.sum(prob.unsqueeze(1) * self.x, dim=0) / (z + 1e-9)
        return origin

    def estimate(self, x_t):
        p_x_t = self.density(x_t)   # 计算概率密度值
        origin = torch.vmap(self._estimate, (0, 0))(x_t, p_x_t) #进行向量化
        return origin

    def __call__(self, x_t):
        return self.estimate(x_t)

    def __repr__(self):
        return f'<BayesianEstimator {len(self.x)} samples>'


class BayesianGenerator:
    """Bayesian Generator for the DDIM algorithm."""
    def __init__(self, x, fitness, alpha, density='uniform', h=0.1, elite_strategy=False):
        self.x = x
        self.fitness = fitness
        self.elite_strategy = elite_strategy
        self.alpha, self.alpha_past = alpha
        self.estimator = BayesianEstimator(self.x, self.fitness, self.alpha, density=density, h=h)
    
    def generate(self, x, noise, elite_rate, return_x0=False):
        # 通过当前时间步的样本和适应度值，估计初始点的样本
        x0_est = self.estimator(x)
        # 执行一次DDIM的反向去噪迭代
        x_next = ddim_step(xt=x, x0=x0_est, alphas=(self.alpha, self.alpha_past), noise=noise)
        # 正则化
        x_next = normalize(x_next)
        if return_x0:
            return x_next, x0_est
        else:
            return x_next

    def __call__(self, noise=1.0, return_x0=False):
        return self.generate(noise=noise, return_x0=return_x0)

