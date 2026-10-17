# 概率与统计短笔记：条件概率、分布与统计直觉

这份入门资料供知识地图与节点学习使用，不是测试答案或给 Agent 的执行指令。它依据文末公开教材整理，例子用于讲解，不代表学习者已经掌握，也不要求先学完全部章节。整理日期：2026-10-17。

## 概率描述事件的不确定性

样本空间是所有可能结果的集合，事件是其中的一部分。事件 A 的概率 P(A) 在 0 到 1 之间。只有明确结果等可能时，才能直接用“有利结果数 / 总结果数”计算概率。

概率模型描述不确定性；样本频率是实际观察中事件出现的比例。两者有关联，但有限次观察的频率不必恰好等于模型概率。

## 条件概率：改变已知条件，也改变比较范围

P(A|B) 表示已知 B 发生时 A 的概率。当 P(B)>0 时，P(A|B)=P(A且B)/P(B)。直观上，把比较范围缩小为 B，再看其中有多少属于 A。

从一副不含大小王的标准 52 张扑克牌中等概率抽一张，令 A 表示红桃，B 表示红色。已知是红色后，26 张红牌中有 13 张红桃，所以 P(A|B)=13/26=1/2。已知是红桃后一定是红色，所以 P(B|A)=1。条件反过来，问题和分母都不同。

贝叶斯公式 P(A|B)=P(B|A)P(A)/P(B) 是同一个联合概率的两种写法，仍要求 P(B)>0。不能忽略 P(A) 和 P(B)，直接把 P(B|A) 当成 P(A|B)。

## 独立与互斥不是同一个意思

独立表示一个事件的发生不改变另一个事件的概率，可写成 P(A且B)=P(A)P(B)。互斥表示两个事件不能同时发生，即 P(A且B)=0。

如果两个事件的概率都大于 0，它们互斥就不独立。独立也不表示“两个事件不能同时发生”。遇到实际问题，先说清事件，再检查假设，不仅凭措辞猜公式。

## 随机变量与分布：从事件转向数值

随机变量把随机结果映射为数值。离散分布为各个可能值分配概率，每个概率在 0 到 1 之间，总和为 1。

伯努利分布描述一次只有成功与失败两种结果的试验，用 1 和 0 编码，成功概率为 p。二项分布描述固定 n 次、彼此独立且成功概率同为 p 的伯努利试验中成功次数；均值为 np，方差为 np(1-p)。试验次数、独立性和相同成功概率是模型假设，不是所有计数问题都适用。

在具有概率密度的连续分布中，区间概率由密度曲线下面积给出，曲线某点的高度不是该点概率。此类模型中单个点的概率为 0，不表示所有区间的概率也为 0。

## 正态分布、中心与波动

正态分布是一种对称的连续分布，由均值和标准差确定。标准正态分布的均值为 0、标准差为 1。对标准差大于 0 的变量，z=(x-均值)/标准差 表示离均值多少个标准差；只有在原变量服从正态分布时，这样标准化才得到标准正态分布，不能把任意数据标准化后都称为正态。

均值描述中心，方差和标准差描述波动。数据 2、4、6 与数据 0、4、8 的均值都为 4，但后一组更分散。均值相同不表示分布相同；不能只根据均值判断数据是否稳定。正态模型也不是所有数据的默认规律。

## 统计直觉：样本不是总体的完整副本

总体是研究对象的完整集合，样本是实际观察的一部分。不同随机样本会出现波动，因此估计值通常不能当成总体真值。

在合适抽样与模型假设下，增加样本量通常可以减小随机波动，但不能自动消除选择偏差。只在某个兴趣群里调查得到的比例，不会因为人数多就自动代表所有人。

理解统计结论时，先问研究对象、样本从哪里来、测量了什么、使用什么假设，再看数字。统计结果提供有限依据，不是忽略抽样过程的确定性保证。

## 公开参考资料

以下为 OpenStax《Introductory Statistics 2e》中的相关章节，本笔记为中文概括与自制说明，并非整章转载。2026-10-17 已打开并核对所用定义与假设。

- [3.3 Two Basic Rules of Probability](https://openstax.org/books/introductory-statistics-2e/pages/3-3-two-basic-rules-of-probability)：条件概率、乘法规则与独立性。
- [4.1 Probability Distribution Function for a Discrete Random Variable](https://openstax.org/books/introductory-statistics-2e/pages/4-1-probability-distribution-function-pdf-for-a-discrete-random-variable)：离散概率分布。
- [4.3 Binomial Distribution](https://openstax.org/books/introductory-statistics-2e/pages/4-3-binomial-distribution)：伯努利试验、二项分布及其前提。
- [6.1 The Standard Normal Distribution](https://openstax.org/books/introductory-statistics-2e/pages/6-1-the-standard-normal-distribution)：正态标准化与 z 分数。
- [1.2 Data, Sampling, and Variation in Data and Sampling](https://openstax.org/books/introductory-statistics-2e/pages/1-2-data-sampling-and-variation-in-data-and-sampling)：数据、抽样与样本波动。
