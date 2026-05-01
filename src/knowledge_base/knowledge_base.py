import os
import re
import pickle
import hashlib
import logging
# faiss-cpu 启动时会通过 logging 打印 GPU 不可用的 INFO 日志，属于正常行为
# 临时提高 root logger 级别压掉这条消息
_root = logging.getLogger()
_orig_level = _root.level
_root.setLevel(logging.WARNING)
import faiss
_root.setLevel(_orig_level)
import numpy as np
import jieba
import httpx
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

@dataclass
class TextChunk:
    """文本块数据结构"""
    content: str
    chapter: int
    start_idx: int
    end_idx: int
    metadata: Dict

class KnowledgeBase:
    def __init__(self, config: Dict, embedding_model, reranker_config: Dict = None):
        self.config = config
        self.embedding_model = embedding_model
        self.chunks: List[TextChunk] = []
        self.index = None
        self.cache_dir = config["cache_dir"]
        self.is_built = False  # 添加构建状态标志
        os.makedirs(self.cache_dir, exist_ok=True)
        self.reranker_config = reranker_config
        self.reranker = None
        self._init_reranker()

    def _init_reranker(self):
        """初始化 Reranker（通过 API 调用，无需下载本地模型）"""
        if not self.reranker_config:
            logging.info("未提供 Reranker 配置，搜索将仅使用向量检索")
            return
        model_name = self.reranker_config.get("model_name", "")
        api_key = self.reranker_config.get("api_key", "")
        base_url = self.reranker_config.get("base_url", "")
        if not model_name or not api_key:
            logging.warning("Reranker 模型名称或 API Key 为空，跳过初始化")
            return
        try:
            self.reranker = {
                "base_url": base_url,
                "api_key": api_key,
                "model_name": model_name,
                "timeout": self.reranker_config.get("timeout", 60),
            }
            logging.info(f"Reranker API 配置初始化成功: {model_name}")
        except Exception as e:
            logging.warning(f"Reranker 初始化失败（将回退到纯向量检索）: {e}")
            self.reranker = None

    def _get_cache_path(self, text: str) -> str:
        """获取缓存文件路径"""
        text_hash = hashlib.md5(text.encode()).hexdigest()
        return os.path.join(self.cache_dir, f"kb_{text_hash}.pkl")
        
    def _chunk_text(self, text: str) -> List[TextChunk]:
        """将文本分割成块"""
        chunk_size = self.config["chunk_size"]
        overlap = self.config["chunk_overlap"]
        chunks = []
        
        # 按章节分割文本（使用正则匹配 "第X章" 格式，避免 "第" 字出现在正文中导致误分割）
        chapters = re.split(r'(?=第\d+章)', text)
        # 过滤空分片
        chapters = [c for c in chapters if c.strip()]
        logging.info(f"文本分割为 {len(chapters)} 个章节")

        # 如果没有找到章节标记，将整个文本作为一个章节处理
        if len(chapters) <= 1:
            chapters = [text]
            start_idx = 0
        else:
            start_idx = 1
            
        for chapter_idx, chapter_content in enumerate(chapters, start_idx):
            try:
                # 处理单个章节
                sentences = list(jieba.cut(chapter_content, cut_all=False))
                
                current_chunk = []
                current_length = 0
                chunk_start_idx = 0
                
                for i, sentence in enumerate(sentences):
                    current_chunk.append(sentence)
                    current_length += len(sentence)
                    
                    # 当达到目标长度时创建新块
                    if current_length >= chunk_size:
                        chunk_text = "".join(current_chunk)
                        if chunk_text.strip():  # 确保块不为空
                            chunk = TextChunk(
                                content=chunk_text,
                                chapter=chapter_idx,
                                start_idx=chunk_start_idx,
                                end_idx=i,
                                metadata={
                                    "chapter_content": chapter_content[:100] + "...",  # 只保存章节开头
                                    "previous_context": "".join(sentences[max(0, chunk_start_idx-10):chunk_start_idx]),
                                    "following_context": "".join(sentences[i+1:min(len(sentences), i+11)])
                                }
                            )
                            chunks.append(chunk)
                            logging.debug(f"创建文本块: 章节={chapter_idx}, 长度={len(chunk_text)}")
                        
                        # 保留重叠部分
                        overlap_start = max(0, len(current_chunk) - overlap)
                        current_chunk = current_chunk[overlap_start:]
                        current_length = sum(len(t) for t in current_chunk)
                        chunk_start_idx = i - len(current_chunk) + 1
                
                # 处理最后一个块
                if current_chunk:
                    chunk_text = "".join(current_chunk)
                    if chunk_text.strip():
                        chunk = TextChunk(
                            content=chunk_text,
                            chapter=chapter_idx,
                            start_idx=chunk_start_idx,
                            end_idx=len(sentences)-1,
                            metadata={
                                "chapter_content": chapter_content[:100] + "...",
                                "previous_context": "".join(sentences[max(0, chunk_start_idx-10):chunk_start_idx]),
                                "following_context": ""
                            }
                        )
                        chunks.append(chunk)

            except Exception as e:
                logging.error(f"处理第 {chapter_idx} 章时出错: {str(e)}")
                continue
            
        logging.info(f"总共创建了 {len(chunks)} 个文本块")
        return chunks
        
    def _find_latest_temp_file(self, cache_path: str) -> Optional[Tuple[str, int]]:
        """查找最新的临时文件"""
        temp_files = []
        for f in os.listdir(self.cache_dir):
            if f.startswith(os.path.basename(cache_path) + ".temp_"):
                try:
                    progress = int(f.split("_")[-1])
                    temp_files.append((os.path.join(self.cache_dir, f), progress))
                except ValueError:
                    continue
        return max(temp_files, key=lambda x: x[1]) if temp_files else None

    def _load_from_temp(self, temp_file: str) -> Tuple[List[TextChunk], List]:
        """从临时文件加载进度"""
        try:
            with open(temp_file, 'rb') as f:
                temp_data = pickle.load(f)
                return temp_data['chunks'], temp_data['vectors']
        except Exception as e:
            logging.error(f"加载临时文件失败: {str(e)}")
            return [], []

    def build(self, text: str, force_rebuild: bool = False):
        """构建知识库"""
        cache_path = self._get_cache_path(text)
        
        # 检查缓存
        if not force_rebuild and os.path.exists(cache_path):
            try:
                with open(cache_path, 'rb') as f:
                    cached_data = pickle.load(f)
                
                # 检查缓存格式兼容性
                if 'original_text' in cached_data and 'embedding_model_name' in cached_data:
                    # 新格式缓存
                    cached_model_name = cached_data.get('embedding_model_name', '')
                    current_model_name = self.embedding_model.model_name
                    
                    if cached_model_name != current_model_name:
                        logging.warning(f"嵌入模型配置已更改：缓存使用 {cached_model_name}，当前使用 {current_model_name}")
                        logging.info("将重新构建知识库以使用新的嵌入模型配置")
                        force_rebuild = True
                    else:
                        self.index = cached_data['index']
                        self.chunks = cached_data['chunks']
                        self.is_built = True
                        logging.info("成功从缓存加载知识库")
                        return
                else:
                    # 旧格式缓存，检查维度兼容性
                    if 'index' in cached_data and 'chunks' in cached_data:
                        self.index = cached_data['index']
                        self.chunks = cached_data['chunks']
                        self.is_built = True
                        logging.info("成功从旧格式缓存加载知识库")
                        return
                    else:
                        logging.warning("缓存格式不完整，将重新构建")
                        force_rebuild = True
                        
            except Exception as e:
                logging.warning(f"加载缓存失败: {e}")
                force_rebuild = True
        
        # 检查是否有临时文件可以恢复
        # 状态变量统一在恢复决策前初始化，避免后续覆盖丢失已恢复内容
        temp_file_info = None if force_rebuild else self._find_latest_temp_file(cache_path)
        start_idx = 0
        vectors: List = []
        valid_chunks: List[TextChunk] = []  # 已成功嵌入的 chunk，与 vectors 严格对齐

        if temp_file_info:
            temp_file, progress = temp_file_info
            logging.info(f"发现临时文件，尝试从进度 {progress} 恢复...")
            restored_chunks, restored_vectors = self._load_from_temp(temp_file)
            if restored_chunks and restored_vectors:
                # 重新分块以获得完整的待处理 chunk 列表（temp 仅含已成功的子集）
                self.chunks = self._chunk_text(text)
                # 将已处理的有效状态注入 valid_chunks/vectors，保证后续追加可对齐
                valid_chunks = list(restored_chunks)
                vectors = list(restored_vectors)
                start_idx = progress
                logging.info(
                    f"成功恢复到进度 {progress}，已注入 {len(valid_chunks)} 个有效 chunk，"
                    f"继续处理剩余内容"
                )
            else:
                logging.warning("临时文件加载失败，将从头开始处理")
                self.chunks = self._chunk_text(text)
        else:
            # 分块
            self.chunks = self._chunk_text(text)

        logging.info(f"创建了 {len(self.chunks)} 个文本块")

        # 分批获取嵌入向量
        # valid_chunks/vectors 在上方已根据是否从临时文件恢复初始化完毕
        batch_size = 100  # 每批处理100个文本块
        total = len(self.chunks)

        for i in range(start_idx, total, batch_size):
            batch_chunks = self.chunks[i:i+batch_size]

            for j, chunk in enumerate(batch_chunks):
                try:
                    vector = self.embedding_model.embed(chunk.content)
                    if vector is None or len(vector) == 0:
                        logging.warning(f"文本块 {i+j} 返回空向量，跳过")
                        continue
                    valid_chunks.append(chunk)
                    vectors.append(vector)
                    logging.info(f"生成文本块 {i+j} 的向量，维度: {len(vector)}")
                except Exception as e:
                    logging.warning(f"生成文本块 {i+j} 的向量时出错: {e}，跳过")
                    continue

            # 定期保存中间结果（使用 valid_chunks 保证对齐）
            # 文件后缀使用 i + batch_size，即下次恢复时的起点 chunk 索引，
            # 避免重启时重复处理已完成批次导致 valid_chunks 出现重复条目
            if i % 1000 == 0 and i > 0:
                next_idx = i + batch_size
                temp_cache_path = cache_path + f".temp_{next_idx}"
                with open(temp_cache_path, 'wb') as f:
                    pickle.dump({
                        'chunks': valid_chunks,
                        'vectors': vectors
                    }, f)
                logging.info(f"保存临时进度到 {temp_cache_path}（下次从 chunk 索引 {next_idx} 继续）")

        # 用有效子集替换 self.chunks，保证 chunks 与 vectors 严格对齐
        self.chunks = valid_chunks
        skipped = total - len(valid_chunks)
        if skipped > 0:
            logging.warning(f"嵌入过程中跳过了 {skipped}/{total} 个文本块")

        if not vectors:
            raise ValueError("没有生成有效的向量")
        
        # 构建索引
        dimension = len(vectors[0])
        logging.info(f"构建 FAISS 索引，维度 {dimension}")
        self.index = faiss.IndexFlatL2(dimension)
        vectors_array = np.array(vectors).astype('float32')
        self.index.add(vectors_array)
        
        # 保存缓存
        with open(cache_path, 'wb') as f:
            pickle.dump({
                'index': self.index,
                'chunks': self.chunks,
                'original_text': text,  # 保存原始文本以便重新构建
                'embedding_model_name': self.embedding_model.model_name,  # 保存嵌入模型名称
                'embedding_dimension': dimension  # 保存嵌入维度
            }, f)
        self.is_built = True
        logging.info("知识库构建完成并已缓存")
        
        # 清理临时文件
        if not self.config.get("keep_temp_files", False):  # 添加配置选项来控制是否保留临时文件
            for f in os.listdir(self.cache_dir):
                if f.startswith(os.path.basename(cache_path) + ".temp_"):
                    try:
                        os.remove(os.path.join(self.cache_dir, f))
                    except Exception as e:
                        logging.warning(f"清理临时文件 {f} 失败: {e}")

    def search(self, query: str, k: int = 5) -> List[str]:
        """搜索相关内容（向量检索 + Reranker 二次精排）"""
        if not self.index:
            logging.error("知识库索引未构建")
            raise ValueError("Knowledge base not built yet")

        query_vector = self.embedding_model.embed(query)

        if query_vector is None:
            logging.error("嵌入模型返回空向量")
            return []

        # 如果有 reranker，多召回一些候选用于精排
        recall_k = min(k * 4, len(self.chunks)) if self.reranker else k

        # 向量检索召回候选
        query_vector_array = np.array([query_vector]).astype('float32')
        distances, indices = self.index.search(query_vector_array, recall_k)

        candidates = []
        for idx in indices[0]:
            if 0 <= idx < len(self.chunks):
                candidates.append(self.chunks[idx].content)

        if not candidates:
            return []

        # Reranker API 二次精排
        if self.reranker and len(candidates) > 1:
            try:
                scores = self._rerank_via_api(query, candidates)
                ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
                results = [doc for doc, _ in ranked[:k]]
                logging.debug(f"Reranker 精排完成，从 {len(candidates)} 个候选中选出 {len(results)} 个")
                return results
            except Exception as e:
                logging.warning(f"Reranker 精排失败，回退到向量检索结果: {e}")

        return candidates[:k]

    def _rerank_via_api(self, query: str, documents: List[str]) -> List[float]:
        """通过 API 调用 Reranker 模型进行精排，返回每个文档的相关性分数"""
        base_url = self.reranker["base_url"].rstrip("/")
        api_key = self.reranker["api_key"]
        model_name = self.reranker["model_name"]
        timeout = self.reranker.get("timeout", 60)

        # SiliconFlow / Jina 兼容的 /rerank 端点
        response = httpx.post(
            f"{base_url}/rerank",
            json={
                "model": model_name,
                "query": query,
                "documents": documents,
                "return_documents": False,
            },
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()

        # 响应格式: {"results": [{"index": 0, "relevance_score": 0.95}, ...]}
        results = data.get("results", [])
        # 按原始文档顺序排列分数
        score_map = {item["index"]: item["relevance_score"] for item in results}
        return [score_map.get(i, 0.0) for i in range(len(documents))]

    def get_all_references(self) -> Dict[str, str]:
        """获取所有参考内容"""
        if not self.chunks:
            return {}
            
        references = {}
        for i, chunk in enumerate(self.chunks):
            key = f"ref_{i+1}"
            references[key] = chunk.content
            
            # 为了避免返回过多数据，只返回前10个参考
            if i >= 9:
                break
                
        return references
        
    def get_context(self, chunk: TextChunk, window_size: int = 2) -> Dict:
        """获取文本块的上下文"""
        chapter = chunk.chapter
        relevant_chunks = [c for c in self.chunks if c.chapter == chapter]
        
        try:
            chunk_idx = relevant_chunks.index(chunk)
        except ValueError:
            return {"previous_chunks": [], "next_chunks": [], "chapter_summary": ""}
        
        context = {
            "previous_chunks": [],
            "next_chunks": [],
            "chapter_summary": chunk.metadata.get("chapter_content", "")
        }
        
        # 获取前文
        start_idx = max(0, chunk_idx - window_size)
        context["previous_chunks"] = relevant_chunks[start_idx:chunk_idx]
        
        # 获取后文
        end_idx = min(len(relevant_chunks), chunk_idx + window_size + 1)
        context["next_chunks"] = relevant_chunks[chunk_idx + 1:end_idx]
        
        return context 

    def build_from_files(self, file_paths: List[str], force_rebuild: bool = False):
        """从多个文件构建知识库"""
        combined_text = ""
        for file_path in file_paths:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    combined_text += f.read() + "\n\n"
                logging.info(f"已加载文件: {file_path}")
            except Exception as e:
                logging.error(f"加载文件 {file_path} 失败: {str(e)}")
                continue
        
        if not combined_text.strip():
            raise ValueError("所有参考文件加载失败，知识库内容为空")
            
        return self.build(combined_text, force_rebuild) 

    def build_from_texts(self, texts: List[str], cache_dir: Optional[str] = None) -> None:
        """从文本列表构建知识库
        
        Args:
            texts: 文本列表，例如章节内容列表
            cache_dir: 缓存目录，如果提供则使用该目录，否则使用默认缓存目录
        """
        if cache_dir:
            old_cache_dir = self.cache_dir
            self.cache_dir = cache_dir
            os.makedirs(self.cache_dir, exist_ok=True)
        
        try:
            # 合并所有文本，加上章节标记
            combined_text = ""
            for i, text in enumerate(texts, 1):
                combined_text += f"第{i}章\n{text}\n\n"
                
            # 使用现有的构建方法
            self.build(combined_text)
            logging.info(f"从 {len(texts)} 个文本构建知识库成功")
            
        except Exception as e:
            logging.error(f"从文本构建知识库时出错: {str(e)}", exc_info=True)
            raise
        finally:
            # 恢复原始缓存目录
            if cache_dir:
                self.cache_dir = old_cache_dir
