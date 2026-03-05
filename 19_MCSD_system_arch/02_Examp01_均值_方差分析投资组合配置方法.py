# This Python file uses the following encoding: utf-8

# if __name__ == "__main__":
#     pass

# python
import pandas as pd

## 阶段一：数据收集与预处理
# 读取5只股票的历史收盘价数据，假设文件名为'stocks.csv'
# CSV格式：日期, A, B, C, D, E
data = pd.read_csv('stocks.csv', index_col=0, parse_dates=True)

# 计算日收益率
returns = data.pct_change().dropna()
print(returns.head())


## 阶段二：统计特征计算
import numpy as np

# 计算平均收益率和标准差
mean_returns = returns.mean()
std_returns = returns.std()

# 计算协方差矩阵
cov_matrix = returns.cov()

print("平均收益率：\n", mean_returns)
print("标准差：\n", std_returns)
print("协方差矩阵：\n", cov_matrix)

## 阶段三：构建投资组合

# 假设初始等权重
weights = np.array([0.2, 0.2, 0.2, 0.2, 0.2])

# 组合预期收益率
portfolio_return = np.dot(weights, mean_returns)

# 组合风险（标准差）
portfolio_std = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))

print(f"组合预期收益率: {portfolio_return:.4f}")
print(f"组合风险（标准差）: {portfolio_std:.4f}")


## 阶段四：优化资产配置（有效前沿）

from scipy.optimize import minimize

# 目标函数：最小化组合风险
def portfolio_volatility(weights, mean_returns, cov_matrix):
    return np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))

# 约束条件：权重和为1
constraints = ({'type': 'eq', 'fun': lambda x: np.sum(x) - 1})

# 权重范围：0~1
bounds = tuple((0, 1) for _ in range(len(mean_returns)))

# 以目标收益率为约束，最小化风险
target_return = 0.10  # 目标年化收益率
def return_constraint(weights):
    return np.dot(weights, mean_returns) - target_return

constraints = (constraints, {'type': 'eq', 'fun': return_constraint})

# 初始猜测
init_guess = len(mean_returns) * [1. / len(mean_returns)]

result = minimize(portfolio_volatility, init_guess, args=(mean_returns, cov_matrix),
                 method='SLSQP', bounds=bounds, constraints=constraints)

optimal_weights = result.x
print("最优权重：", optimal_weights)


## 阶段五：风险评估与决策


# 计算最优组合的收益和风险
opt_return = np.dot(optimal_weights, mean_returns)
opt_std = np.sqrt(np.dot(optimal_weights.T, np.dot(cov_matrix, optimal_weights)))

# 夏普比率（假设无风险利率为0.02）
rf = 0.02
sharpe_ratio = (opt_return - rf) / opt_std

print(f"最优组合收益率: {opt_return:.4f}")
print(f"最优组合风险: {opt_std:.4f}")
print(f"夏普比率: {sharpe_ratio:.4f}")

# VaR（95%置信水平，正态分布假设）
from scipy.stats import norm
VaR_95 = opt_return - norm.ppf(0.95) * opt_std
print(f"95% VaR: {VaR_95:.4f}")

## 阶段六：投资执行与后续跟踪

# 实际投资时，将资金按optimal_weights分配到各股票
# 后续跟踪：定期（如每月）重新计算权重，进行组合再平衡

# 示例：每月再平衡
rebalance_dates = returns.resample('M').last().index
for date in rebalance_dates:
    # 取到当前日期为止的数据
    sub_returns = returns.loc[:date]
    mean_returns = sub_returns.mean()
    cov_matrix = sub_returns.cov()
    # 重新优化权重（同上）
    # ...（同上优化代码）
    # 记录权重，进行再平衡
