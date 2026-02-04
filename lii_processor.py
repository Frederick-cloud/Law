import re
import psycopg2
from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import DocItemLabel

# ==========================================
# 1. 核心工具：中文数字转整数 (支持到百位)
# ==========================================
CN_NUM = {'零': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}


def cn_to_int(cn):
    """将'第一百二十三'这种格式解析为 123，确保 URI 的唯一性"""
    if not cn: return 0
    res, temp = 0, 0
    for char in cn:
        if char == '百':
            res += (temp if temp != 0 else 1) * 100
            temp = 0
        elif char == '十':
            res += (temp if temp != 0 else 1) * 10
            temp = 0
        else:
            temp = CN_NUM.get(char, 0)
    return res + temp


# ==========================================
# 2. 法律结构化解析引擎 (仿 Cornell LII)
# ==========================================
class LegalStructureEngine:
    def __init__(self, db_config):
        self.converter = DocumentConverter()
        try:
            self.conn = psycopg2.connect(**db_config)
            self.cur = self.conn.cursor()
            print("✅ 数据库连接成功")
        except Exception as e:
            print(f"❌ 数据库连接失败: {e}")
            raise

    def parse_and_store(self, file_path, doc_id, metadata):
        """核心解析逻辑：解决章节遗漏与颗粒度问题"""
        print(f"🚀 正在处理文档: {metadata['title']} ...")

        # Docling 视觉解析
        result = self.converter.convert(file_path)
        doc = result.document

        # 写入元数据 (Dublin Core)
        self.cur.execute("""
            INSERT INTO legal_metadata (doc_id, title, creator, pub_date)
            VALUES (%s, %s, %s, %s) 
            ON CONFLICT (doc_id) DO UPDATE SET title = EXCLUDED.title;
        """, (doc_id, metadata['title'], metadata['creator'], metadata['date']))

        current_c_uri = None  # 当前章节 URI (如 /fxqf/c1)
        active_uri = None  # 当前活跃节点 (可能是章或条)
        has_entered_body = False  # 跳过目录的关键开关

        print("🔄 正在进行逻辑重塑与层级映射...")

        # 线性遍历文档对象流
        for item, level in doc.iterate_items():
            if not hasattr(item, "text") or not item.text:
                continue

            text = item.text.strip()

            # --- A. 识别章节 (Chapter) ---
            # 解决第三章丢失：不再只认 SECTION_HEADER，兼容所有标签
            c_match = re.match(r'^第([一二三四五六七八九十百]+)章', text)
            if c_match:
                c_num_str = c_match.group(1)
                c_val = cn_to_int(c_num_str)

                # 智能目录过滤：如果看到第一章且后面紧跟目录特征，则不设为正文
                if not has_entered_body and ("目录" in text or "..." in text):
                    continue

                current_c_uri = f"/{doc_id.lower()}/c{c_val}"
                active_uri = current_c_uri

                # === 🚩 修复核心：检测“章”和“条”是否粘连 ===
                # 在当前文本中寻找是否存在“第X条”开始的迹象（利用空格或换行作为分隔特征）
                # 正则解释：查找空格后紧跟“第X条”的模式
                section_split = re.search(r'[\s\n]+(第[0-9一二三四五六七八九十百]+条)', text)

                if section_split:
                    # ✅ 发现粘连！进行手术切割
                    split_idx = section_split.start()  # 获取切割点

                    # 1. 截取前半部分作为章节标题（例如："第一章 总则"）
                    chapter_title = text[:split_idx].strip()
                    self._save_node(doc_id, current_c_uri, "chapter", c_val, chapter_title, None)

                    # 2. 【关键】更新 text 为后半部分（例如："第一条 为了..."）
                    text = text[split_idx:].strip()
                    print(f"✂️ 自动拆分粘连章节: [{chapter_title}] <-> [{text[:10]}...]")

                    # 3. ⚠️ 这里绝对不能 continue！
                    # 让代码继续往下走，流转到 "--- B. 识别条文 ---"，从而正确生成 a1 节点
                else:
                    # 正常情况：只有章节标题，没有粘连
                    self._save_node(doc_id, current_c_uri, "chapter", c_val, text, None)
                    continue  # 正常结束本次循环

            # --- B. 识别条文 (Section) ---
            # 解决颗粒度问题：只要以“第X条”开头，无论 Docling 如何打标，强行切分
            a_match = re.match(r'^第([0-9一二三四五六七八九十百]+)条', text)
            if a_match:
                has_entered_body = True  # 发现条文，彻底进入正文模式

                a_num_str = a_match.group(1)
                a_val = int(a_num_str) if a_num_str.isdigit() else cn_to_int(a_num_str)

                # 容错：防止第一章被漏掉导致 current_c_uri 为空
                if not current_c_uri:
                    current_c_uri = f"/{doc_id.lower()}/c1"

                article_uri = f"{current_c_uri}/a{a_val}"
                active_uri = article_uri

                # 存储条文节点，parent_uri 指向章
                self._save_node(doc_id, article_uri, "section", a_val, text, current_c_uri)
                continue

            # --- C. 内容追加 (Append Content) ---
            # 解决只有名称没有正文的问题：将内容追加到 active_uri 对应的节点
            if has_entered_body and active_uri:
                # 过滤常见物理噪声
                if re.match(r'^(证监会|页码|\[source|中华人民共和国|第.*页|-\s*\d+\s*-)', text):
                    continue

                # 清洗文本并追加
                cleaned = text.replace('\n', '').replace(' ', '')
                self.cur.execute("""
                    UPDATE legal_nodes SET content = content || %s 
                    WHERE uri = %s
                """, ("\n" + cleaned, active_uri))

        self.conn.commit()
        print(f"✅ {doc_id} 已解析为 LII 结构化数据，共计完成颗粒度切分。")

    def _save_node(self, doc_id, uri, label, num, content, parent):
        self.cur.execute("""
            INSERT INTO legal_nodes (doc_id, uri, label, num_val, content, parent_uri)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (uri) DO UPDATE 
            SET content = EXCLUDED.content, parent_uri = EXCLUDED.parent_uri, label = EXCLUDED.label;
        """, (doc_id, uri, label, num, content, parent))


# ==========================================
# 3. 执行入口
# ==========================================
if __name__ == "__main__":
    # 配置你的 PostgreSQL 密码
    my_db_config = {
        "dbname": "legal_db",
        "user": "postgres",
        "password": "123456",
        "host": "127.0.0.1",
        "port": "5432"
    }

    engine = LegalStructureEngine(my_db_config)

    # [cite_start]处理《反洗钱法》 [cite: 1-173]
    engine.parse_and_store(
        file_path="./部分2020年后外规/中华人民共和国公司法_20231229.docx",
        doc_id="GSF",
        metadata={
            "title": "中华人民共和国公司法",
            "creator": "全国人大常委会",
            "date": "2023-12-29"
        }
    )