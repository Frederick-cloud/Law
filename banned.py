import pandas as pd


def process_law_evolution(input_file, output_file):
    print(f"--- 开始处理文件: {input_file} ---")

    # 1. 加载原始数据
    # 使用 xlrd 引擎读取 .xls 文件
    try:
        df = pd.read_excel(input_file)
    except Exception as e:
        print(f"读取失败，请确保已安装 xlrd (pip install xlrd)。错误信息: {e}")
        return

    total_count = len(df)
    print(f"【初始状态】原始数据总条数: {total_count} 条")

    # 2. 逻辑第一步：判断是否是 'Y'
    # 过滤 '是否废除旧法规' 列
    df_step1 = df[df['是否废除旧法规'] == 'Y'].copy()
    count_step1 = len(df_step1)
    print(f"【筛选1】'是否废除旧法规' 为 'Y' 的条数: {count_step1} 条")

    # 3. 逻辑第二步：判断 '废除的法律法规编号' 是否为空
    # 同时过滤 NaN、空字符串、以及只含空格的无效条目
    df_step2 = df_step1[
        df_step1['废除的法律法规编号'].notna() &
        (df_step1['废除的法律法规编号'].astype(str).str.strip() != '')
        ].copy()
    count_step2 = len(df_step2)
    print(f"【筛选2】在 Y 的基础上，'废除编号' 不为空的条数: {count_step2} 条")

    # 4. 逻辑第三步：合并信息（获取旧规名称并整合成一条数据）
    # 首先建立一个“编号 -> 名称”的快速查找表（利用原始 df 的所有数据）
    name_map = df[['编号', '法律法规名称']].dropna(subset=['编号']).set_index('编号')['法律法规名称'].to_dict()

    # 格式化编号，防止因前后空格导致匹配失败
    df_step2['废除的法律法规编号'] = df_step2['废除的法律法规编号'].astype(str).str.strip()

    # 提取并重命名列
    # 注意：如果你的表里“生效时间”叫其他名字（如“实施日期”），请修改此处
    effective_col = '实施日期' if '实施日期' in df.columns else '发布日期'

    # 构造最终的 DataFrame
    result = pd.DataFrame({
        '新规编号': df_step2['编号'],
        '新规名称': df_step2['法律法规名称'],
        '新规发布时间': df_step2['发布日期'],
        '新规生效时间': df_step2[effective_col],
        '旧规编号': df_step2['废除的法律法规编号'],
        '旧规名称': df_step2['废除的法律法规编号'].map(name_map)  # 核心逻辑：通过编号找回旧规名称
    })

    # 统计最终匹配结果
    matched_count = result['旧规名称'].notna().sum()
    unmatched_count = result['旧规名称'].isna().sum()

    print(f"【合并结果】成功匹配到旧规名称的条数: {matched_count} 条")
    if unmatched_count > 0:
        print(f"【警告】有 {unmatched_count} 条旧规编号在原表中找不到对应的名称（可能旧规不在本表内）")

    # 5. 保存结果
    result.to_excel(output_file, index=False)
    print(f"--- 处理完成！结果已保存至: {output_file} ---")


# 执行
if __name__ == "__main__":
    process_law_evolution('法律法规导出包.xls', '法规演化对照表.xlsx')