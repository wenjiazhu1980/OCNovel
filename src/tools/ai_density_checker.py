# -*- coding: utf-8 -*-
"""
AI浓度检测工具
用于评估生成内容的AI痕迹程度
"""

import re
from typing import Dict, List, Tuple

class EnhancedAIDensityChecker:
    """增强版AI浓度检测器，支持多维度检测和朱雀AI适配"""
    
    def __init__(self):
        # 扩展AI化词汇库
        self.ai_patterns = {
            'transition_words': [
                "与此同时", "伴随着", "紧接着", "毫无疑问", "显而易见",
                "不言而喻", "众所周知", "毋庸置疑", "无可否认", "随即",
                "顿时", "瞬间", "刹那间", "霎时间", "刹那之间", "须臾间",
                "蓦然", "忽然间", "旋即", "继而", "进而", "然而", "因此",
                "所以", "于是", "接下来", "随后", "紧随其后", "与之相对"
            ],
            'formal_expressions': [
                "毋庸置疑", "显而易见", "不言而喻", "理所当然", "自然而然",
                "无可厚非", "毫无疑问", "不容置疑", "众所周知", "事实上",
                "确实如此", "毫无例外", "无一例外", "不可否认", "必须承认",
                "不得不说", "可想而知", "显然", "明显", "当然", "无疑",
                "必然", "势必", "定然", "果然", "果不其然"
            ],
            'technical_terms': [
                "数据流", "算法", "系统", "程序", "代码", "协议", "接口",
                "量子", "维度", "频率", "波长", "能量场", "磁场", "电磁",
                "逻辑", "机制", "模式", "体系", "框架", "结构", "模块",
                "参数", "配置", "组件", "元素", "单元", "节点", "网络"
            ],
            'perfect_descriptions': [
                "璀璨", "绚烂", "瑰丽", "恢弘", "磅礴", "浩瀚", "无垠",
                "深邃", "神秘", "玄妙", "奥秘", "精妙", "巧妙", "绝妙",
                "完美", "极致", "无懈可击", "天衣无缝", "精准", "准确",
                "严密", "精确", "缜密", "细致", "精细", "详尽", "透彻"
            ],
            'abstract_concepts': [
                "概念", "本质", "核心", "深层", "根本", "终极", "绝对",
                "无限", "永恒", "至高", "超越", "升华", "涅槃", "境界",
                "层面", "维度", "角度", "视角", "范畴", "领域", "范围"
            ]
        }
        
        # AI句式模式（正则表达式）
        self.ai_sentence_patterns = [
            r'.*过程中.*',
            r'.*的同时.*',
            r'.*伴随着.*',
            r'.*只见.*轻轻.*',
            r'.*瞬间.*',
            r'.*刹那.*',
            r'.*顿时.*',
            r'.*霎时.*'
        ]
        
        # 自然化表达库
        self.natural_patterns = {
            'casual_words': ["然后", "接着", "突然", "没想到", "结果", "谁知道", "竟然", "正好", "刚好", "恰好"],
            'colloquial': ["这玩意儿", "什么鬼", "搞什么", "怎么回事", "管他呢", "算了吧", "别提了", "可别说", "真的假的", "搞不懂"],
            'filler_words': ["呃", "那个", "嗯", "怎么说呢", "哎呀", "哟", "嘿", "这个", "不是", "那个啥", "这样吧", "你知道吗", "其实", "说实话", "老实说"],
            'body_language': ["挠头", "叹气", "翻白眼", "耸肩", "摆手", "拍拍", "摸摸", "挥手", "摇手", "敲头", "拍脑袋", "挠手顿足", "摇头", "点头"],
            'natural_emotions': ["郁闷", "纠结", "懵逼", "无语", "尴尬", "无奈", "吐槽", "无聊", "焦虑", "忙忙", "墨迹", "麻烦", "头疼", "疑惑", "迷茫", "不解"],
            'dialogue_markers': ["说", "道", "问", "答", "喊", "叫", "嘟囔", "嘀咕", "抱怨", "叹息", "嘀哝", "嘲哝", "无奈地说", "叽叽呱呱", "轻声道"],
            'uncertainty_words': ["大概", "可能", "也许", "估计", "好像", "似乎", "应该", "可能是", "不太确定", "不大清楚", "难说", "不好说"],
            'pause_words': ["就是", "就是说", "没错", "对吧", "你知道的", "怎么说", "这样子", "那个意思", "就这样"]
        }
        
        # 朱雀AI检测敏感特征
        self.zhuque_sensitive_patterns = {
            'repetitive_structures': [],  # 重复结构
            'formal_transitions': [],     # 正式转折
            'perfect_descriptions': [],   # 完美描述
            'lack_of_hesitation': [],    # 缺乏犹豫
            'technical_precision': []     # 技术精确性
        }
    
    def check_density(self, text: str) -> Dict:
        """
        增强版AI浓度检测
        
        Args:
            text: 待检测的文本
            
        Returns:
            包含详细检测结果的字典
        """
        # 基础统计
        total_chars = len(text)
        total_words = len(re.findall(r'[\u4e00-\u9fff]+', text))
        sentences = self._split_sentences(text)
        
        # 多维度分析
        scores = {
            'ai_vocabulary_score': self._analyze_ai_vocabulary(text),
            'sentence_pattern_score': self._analyze_sentence_patterns(text),
            'dialogue_naturality_score': self._analyze_dialogue_naturality(text),
            'emotional_authenticity_score': self._analyze_emotional_authenticity(text),
            'linguistic_variation_score': self._analyze_linguistic_variation(text)
        }
        
        # 加权计算总分
        weights = {
            'ai_vocabulary_score': 0.25,
            'sentence_pattern_score': 0.20,
            'dialogue_naturality_score': 0.25,
            'emotional_authenticity_score': 0.15,
            'linguistic_variation_score': 0.15
        }
        
        total_score = sum(scores[key] * weights[key] for key in scores)
        
        # 朱雀AI检测适配
        zhuque_analysis = self._optimize_for_zhuque_detection(text)
        
        return {
            'total_score': min(total_score, 100),
            'dimension_scores': scores,
            'zhuque_analysis': zhuque_analysis,
            'detailed_analysis': self._generate_detailed_analysis(text, scores),
            'improvement_suggestions': self._generate_improvement_suggestions(scores),
            'high_risk_features': self._identify_high_risk_features(text, scores)
        }
    
    def _split_sentences(self, text: str) -> List[str]:
        """分割句子"""
        return re.split(r'[。！？]', text)
    
    def _analyze_ai_vocabulary(self, text: str) -> float:
        """分析AI词汇密度"""
        total_words = len(re.findall(r'[\u4e00-\u9fff]+', text))
        if total_words == 0:
            return 0
        
        ai_count = 0
        for category in self.ai_patterns.values():
            for word in category:
                ai_count += text.count(word)
        
        # AI词汇密度越高，分数越高
        density = (ai_count / total_words) * 100
        return min(density * 5, 100)  # 放大系数
    
    def _analyze_sentence_patterns(self, text: str) -> float:
        """分析句式模式"""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0
        
        ai_pattern_count = 0
        for sentence in sentences:
            for pattern in self.ai_sentence_patterns:
                if re.search(pattern, sentence):
                    ai_pattern_count += 1
                    break
        
        pattern_ratio = ai_pattern_count / len(sentences)
        return pattern_ratio * 100
    
    def _analyze_dialogue_naturality(self, text: str) -> float:
        """分析对话自然度"""
        # 检测对话比例 - 修正正则表达式以正确识别中文引号和冒号对话
        # 引号对话："对话内容" 或 "对话内容" 或 '对话内容' 或 '对话内容'
        dialogue_quotes = re.findall(r'["“‘][^"\u201d\u2019]*["”’]', text)
        # 冒号对话：某某道："对话内容"
        dialogue_colons = re.findall(r'[道说问答喝叫嚎囔抱怨]："[^"]*"', text)
        
        all_dialogues = dialogue_quotes + dialogue_colons
        dialogue_chars = sum(len(match) for match in all_dialogues)
        total_chars = len(text)
        
        if total_chars == 0:
            return 100  # 无内容返回高分
        
        dialogue_ratio = dialogue_chars / total_chars
        
        # 检测对话中的自然化表达
        dialogue_text = ' '.join(all_dialogues)
        natural_dialogue_count = 0
        for category in ['filler_words', 'uncertainty_words', 'natural_emotions']:
            for word in self.natural_patterns[category]:
                natural_dialogue_count += dialogue_text.count(word)
        
        # 综合评分：对话数量 + 对话质量
        quantity_score = 0
        if dialogue_ratio < 0.1:  # 对话低于10%
            quantity_score = 80
        elif dialogue_ratio < 0.3:  # 对话低于30%
            quantity_score = 50
        elif dialogue_ratio < 0.4:  # 对话低于40%
            quantity_score = 30
        else:
            quantity_score = 10
        
        # 对话质量评分：缺乏自然表达的对话也是AI化的
        quality_score = 0
        if len(all_dialogues) > 0:
            natural_ratio = natural_dialogue_count / len(dialogue_text) if dialogue_text else 0
            if natural_ratio < 0.01:
                quality_score = 40  # 对话缺乏自然表达
            elif natural_ratio < 0.02:
                quality_score = 20
            else:
                quality_score = 0
        
        return min(quantity_score + quality_score, 100)
    
    def _analyze_emotional_authenticity(self, text: str) -> float:
        """分析情感真实度"""
        # 检测自然情感表达
        natural_emotion_count = 0
        perfect_emotion_count = 0
        
        for emotion in self.natural_patterns['natural_emotions']:
            natural_emotion_count += text.count(emotion)
        
        for desc in self.ai_patterns['perfect_descriptions']:
            perfect_emotion_count += text.count(desc)
        
        total_words = len(re.findall(r'[\u4e00-\u9fff]+', text))
        if total_words == 0:
            return 0
        
        # 自然情感越多分数越低，完美描述越多分数越高
        natural_ratio = natural_emotion_count / total_words
        perfect_ratio = perfect_emotion_count / total_words
        
        score = (perfect_ratio * 100) - (natural_ratio * 50)
        return max(0, min(score, 100))
    
    def _analyze_linguistic_variation(self, text: str) -> float:
        """分析语言变化度"""
        sentences = self._split_sentences(text)
        if len(sentences) < 2:
            return 0
        
        # 检测句子长度变化
        lengths = [len(s) for s in sentences if s.strip()]
        if not lengths:
            return 100
        
        avg_length = sum(lengths) / len(lengths)
        variance = sum((l - avg_length) ** 2 for l in lengths) / len(lengths)
        
        # 方差越小，变化度越低，AI化越高
        if variance < 50:  # 句子长度过于一致
            return 80
        elif variance < 100:
            return 60
        elif variance < 200:
            return 40
        else:
            return 20
    
    def _optimize_for_zhuque_detection(self, text: str) -> Dict:
        """针对朱雀AI检测的特殊优化"""
        zhuque_features = {
            'repetitive_structures': self._detect_repetitive_structures(text),
            'formal_transitions': self._detect_formal_transitions(text),
            'perfect_descriptions': self._detect_perfect_descriptions(text),
            'lack_of_hesitation': self._detect_lack_of_hesitation(text),
            'technical_precision': self._detect_technical_precision(text)
        }
        
        # 优化权重计算，降低重复结构权重，重点关注缺乏犹豫
        weights = {
            'lack_of_hesitation': 0.35,  # 降低权重从40%到35%
            'repetitive_structures': 0.20,  # 降低权重从25%到20%
            'formal_transitions': 0.20,  # 提高权重从15%到20%
            'perfect_descriptions': 0.15,  # 提高权重从10%到15%
            'technical_precision': 0.10   # 保持10%
        }
        
        risk_score = sum(zhuque_features[k] * weights[k] for k in zhuque_features)
        
        return {
            'zhuque_risk_score': min(risk_score, 100),
            'high_risk_features': [k for k, v in zhuque_features.items() if v > 60],
            'feature_scores': zhuque_features,
            'targeted_suggestions': self._generate_zhuque_optimizations(zhuque_features)
        }
    
    def _detect_repetitive_structures(self, text: str) -> float:
        """检测重复结构"""
        sentences = self._split_sentences(text)
        if len(sentences) < 3:
            return 0
        
        # 检测相似句式结构
        patterns = []
        for sentence in sentences:
            if len(sentence.strip()) < 3:  # 忽略太短的句子
                continue
            # 提取句式结构（去除具体词汇）
            pattern = re.sub(r'[\u4e00-\u9fff]+', 'X', sentence)
            # 简化标点符号
            pattern = re.sub(r'[\uff0c\u3002\uff1f\uff01\uff1a\uff1b]+', 'P', pattern)
            patterns.append(pattern)
        
        if len(patterns) == 0:
            return 0
            
        # 计算重复率，考虑相似模式
        unique_patterns = set(patterns)
        pattern_counts = {}
        for pattern in patterns:
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
        
        # 找出重复超过一次的模式
        repeated_count = sum(count - 1 for count in pattern_counts.values() if count > 1)
        repetition_ratio = repeated_count / len(patterns) if patterns else 0
        
        return min(repetition_ratio * 120, 100)  # 降低放大系数从150到120
    
    def _detect_formal_transitions(self, text: str) -> float:
        """检测正式转折词"""
        formal_count = 0
        for word in self.ai_patterns['transition_words']:
            formal_count += text.count(word)
        
        total_words = len(re.findall(r'[\u4e00-\u9fff]+', text))
        if total_words == 0:
            return 0
        
        ratio = formal_count / total_words
        return min(ratio * 200, 100)  # 放大系数
    
    def _detect_perfect_descriptions(self, text: str) -> float:
        """检测完美描述"""
        perfect_count = 0
        for word in self.ai_patterns['perfect_descriptions']:
            perfect_count += text.count(word)
        
        total_words = len(re.findall(r'[\u4e00-\u9fff]+', text))
        if total_words == 0:
            return 0
        
        ratio = perfect_count / total_words
        return min(ratio * 150, 100)
    
    def _detect_lack_of_hesitation(self, text: str) -> float:
        """检测缺乏犹豫和停顿"""
        # 扩展犹豫标记词，包括多种自然化表达
        hesitation_markers = (
            self.natural_patterns['filler_words'] + 
            self.natural_patterns['uncertainty_words'] + 
            self.natural_patterns['pause_words'] +
            self.natural_patterns['natural_emotions']  # 加入情感词汇
        )
        
        hesitation_count = 0
        for marker in hesitation_markers:
            hesitation_count += text.count(marker)
        
        # 计算总词汇数（中文字符）
        total_words = len(re.findall(r'[\u4e00-\u9fff]+', text))
        if total_words == 0:
            return 100
        
        hesitation_ratio = hesitation_count / total_words
        
        # 优化评分算法，更反映真实情况，降低高分阈值
        if hesitation_ratio < 0.003:  # 少于0.3%，非常缺乏（从0.5%降低）
            return 90  # 从95降低到9
        elif hesitation_ratio < 0.008:  # 少于0.8%，严重缺乏（从1%降低）
            return 75  # 从85降低到75
        elif hesitation_ratio < 0.015:  # 少于1.5%，明显缺乏（从2%降低）
            return 60  # 从70降低到60
        elif hesitation_ratio < 0.025:  # 少于2.5%，轻度缺乏（从3%降低）
            return 40  # 从50降低到40
        elif hesitation_ratio < 0.040:  # 少于4%，较好（从5%降低）
            return 25  # 从30降低到25
        else:
            return 10  # 充足的自然表达
    
    def _detect_technical_precision(self, text: str) -> float:
        """检测技术精确性"""
        technical_count = 0
        for word in self.ai_patterns['technical_terms']:
            technical_count += text.count(word)
        
        total_words = len(re.findall(r'[\u4e00-\u9fff]+', text))
        if total_words == 0:
            return 0
        
        ratio = technical_count / total_words
        return min(ratio * 100, 100)
    
    def _generate_detailed_analysis(self, text: str, scores: Dict) -> Dict:
        """生成详细分析报告"""
        total_words = len(re.findall(r'[\u4e00-\u9fff]+', text))
        sentences = self._split_sentences(text)
        # 修正对话检测正则表达式，同时支持中文引号和冒号对话
        dialogue_quotes = re.findall(r'["“‘][^"\u201d\u2019]*["”’]', text)
        dialogue_colons = re.findall(r'[道说问答喝叫噎嚷抱怨]："[^"]*"', text)
        dialogue_matches = dialogue_quotes + dialogue_colons

        return {
            'text_stats': {
                'total_words': total_words,
                'total_sentences': len(sentences),
                'avg_sentence_length': total_words / len(sentences) if sentences else 0,
                'dialogue_count': len(dialogue_matches),
                'dialogue_ratio': sum(len(d) for d in dialogue_matches) / len(text) if text else 0
            },
            'ai_features': self._extract_ai_features(text),
            'natural_features': self._extract_natural_features(text),
            'risk_assessment': self._assess_risks(scores)
        }
    
    def _extract_ai_features(self, text: str) -> Dict:
        """提取AI化特征"""
        ai_words_found = []
        for category, words in self.ai_patterns.items():
            for word in words:
                count = text.count(word)
                if count > 0:
                    ai_words_found.append((word, count, category))
        
        return {
            'ai_words': ai_words_found,
            'total_ai_words': sum(count for _, count, _ in ai_words_found),
            'categories': list(set(cat for _, _, cat in ai_words_found))
        }
    
    def _extract_natural_features(self, text: str) -> Dict:
        """提取自然化特征"""
        natural_words_found = []
        for category, words in self.natural_patterns.items():
            for word in words:
                count = text.count(word)
                if count > 0:
                    natural_words_found.append((word, count, category))
        
        return {
            'natural_words': natural_words_found,
            'total_natural_words': sum(count for _, count, _ in natural_words_found),
            'categories': list(set(cat for _, _, cat in natural_words_found))
        }
    
    def _assess_risks(self, scores: Dict) -> List[str]:
        """评估风险等级"""
        risks = []
        
        if scores['ai_vocabulary_score'] > 60:
            risks.append('AI词汇密度过高')
        if scores['sentence_pattern_score'] > 60:
            risks.append('句式结构过于规范')
        if scores['dialogue_naturality_score'] > 60:
            risks.append('对话不够自然')
        if scores['emotional_authenticity_score'] > 60:
            risks.append('情感表达不够真实')
        if scores['linguistic_variation_score'] > 60:
            risks.append('语言变化度不够')
        
        return risks
    
    def _generate_improvement_suggestions(self, scores: Dict) -> List[str]:
        """生成改进建议"""
        suggestions = []
        
        if scores['dialogue_naturality_score'] > 40:
            suggestions.append('大幅增加人物对话，目标比例40%以上')
        
        if scores['ai_vocabulary_score'] > 40:
            suggestions.append('替换AI化词汇：伴随着→然后、与此同时→这时候')
        
        if scores['sentence_pattern_score'] > 40:
            suggestions.append('使用更多不完整句子和口语化表达')
        
        if scores['emotional_authenticity_score'] > 40:
            suggestions.append('增加真实情感：犹豫、矛盾、尴尬等')
        
        if scores['linguistic_variation_score'] > 40:
            suggestions.append('增加语言变化，避免句式重复')
        
        return suggestions
    
    def _identify_high_risk_features(self, text: str, scores: Dict) -> List[str]:
        """识别高风险特征"""
        high_risk = []
        
        # 检测对话缺失 - 修正对话检测正则表达式，支持中文引号和冒号对话
        dialogue_quotes = re.findall(r'["“‘][^"\u201d\u2019]*["”’]', text)
        dialogue_colons = re.findall(r'[道说问答喝叫噎嚷抱怨]："[^"]*"', text)
        all_dialogues = dialogue_quotes + dialogue_colons
        dialogue_chars = sum(len(match) for match in all_dialogues)
        dialogue_ratio = dialogue_chars / len(text) if text else 0
        if dialogue_ratio < 0.1:
            high_risk.append('对话比例严重偏低')
        
        # 检测高频AI词汇
        ai_words = []
        for category, words in self.ai_patterns.items():
            for word in words:
                if text.count(word) > 1:
                    ai_words.append(word)
        
        if ai_words:
            high_risk.append(f'AI词汇高频出现：{", ".join(ai_words[:3])}')
        
        # 检测缺乏自然表达
        natural_count = 0
        for category, words in self.natural_patterns.items():
            for word in words:
                natural_count += text.count(word)
        
        if natural_count == 0:
            high_risk.append('缺乏自然化表达')
        
        return high_risk
    
    def _generate_zhuque_optimizations(self, features: Dict) -> List[str]:
        """生成朱雀AI检测优化建议"""
        suggestions = []
        
        if features['repetitive_structures'] > 50:
            suggestions.append('减少重复句式，增加语言变化')
        
        if features['formal_transitions'] > 50:
            suggestions.append('用口语化转折词替换正式表达')
        
        if features['perfect_descriptions'] > 50:
            suggestions.append('用简单直接的描述替换华丽词汇')
        
        if features['lack_of_hesitation'] > 70:
            suggestions.append('增加犹豫词：呃、那个、怎么说呢')
        
        if features['technical_precision'] > 50:
            suggestions.append('用大白话解释技术性内容')
        
        return suggestions

# 向后兼容的原有类
class AIDensityChecker:
    """原有的AI密度检测器，保持向后兼容"""
    
    def __init__(self):
        self.enhanced_checker = EnhancedAIDensityChecker()
        
        # 保持原有的属性结构
        self.ai_keywords = []
        for category in self.enhanced_checker.ai_patterns.values():
            self.ai_keywords.extend(category)
        
        self.natural_keywords = []
        for category in self.enhanced_checker.natural_patterns.values():
            self.natural_keywords.extend(category)
    
    def check_density(self, text: str) -> Dict:
        """保持原有接口的密度检测"""
        # 使用增强版检测器
        enhanced_result = self.enhanced_checker.check_density(text)
        
        # 转换为原有格式
        total_words = len(re.findall(r'[\u4e00-\u9fff]+', text))
        
        # 统计AI和自然词汇
        ai_found = []
        for keyword in self.ai_keywords:
            count = text.count(keyword)
            if count > 0:
                ai_found.append((keyword, count))
        
        natural_found = []
        for keyword in self.natural_keywords:
            count = text.count(keyword)
            if count > 0:
                natural_found.append((keyword, count))
        
        # 计算对话比例 - 修正为同时检测中文引号和冒号对话
        dialogue_quotes = re.findall(r'["“‘][^"\u201d\u2019]*["”’]', text)
        dialogue_colons = re.findall(r'[道说问答喝叫噎嚷抱怨]："[^"]*"', text)
        all_dialogues = dialogue_quotes + dialogue_colons
        dialogue_chars = sum(len(match) for match in all_dialogues)
        dialogue_ratio = dialogue_chars / len(text) if text else 0
        
        # 计算长句比例
        sentences = re.split(r'[。！？]', text)
        long_sentences = [s for s in sentences if len(s) > 30]
        long_sentence_ratio = len(long_sentences) / len(sentences) if sentences else 0
        
        return {
            "ai_density_score": enhanced_result['total_score'],
            "total_words": total_words,
            "ai_keywords_found": ai_found,
            "natural_keywords_found": natural_found,
            "dialogue_ratio": dialogue_ratio,
            "long_sentence_ratio": long_sentence_ratio,
            "assessment": self._get_assessment(enhanced_result['total_score']),
            "suggestions": enhanced_result['improvement_suggestions'][:3]  # 限制建议数量
        }
    
    def _get_assessment(self, score: float) -> str:
        """根据分数给出评估"""
        if score <= 20:
            return "自然度很高，AI痕迹很少"
        elif score <= 40:
            return "自然度较高，有轻微AI痕迹"
        elif score <= 60:
            return "自然度一般，AI痕迹明显"
        elif score <= 80:
            return "AI痕迹较重，需要优化"
        else:
            return "AI痕迹很重，急需改进"

def check_enhanced_ai_density(text: str) -> Dict:
    """
    使用增强版检测器检测AI密度
    
    Args:
        text: 待检测的文本
        
    Returns:
        详细的检测结果
    """
    checker = EnhancedAIDensityChecker()
    return checker.check_density(text)

def check_chapter_ai_density(chapter_file: str) -> Dict:
    """
    检测章节文件的AI浓度
    
    Args:
        chapter_file: 章节文件路径
        
    Returns:
        检测结果字典
    """
    try:
        with open(chapter_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        checker = AIDensityChecker()
        result = checker.check_density(content)
        result['file_path'] = chapter_file
        
        return result
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    # 测试用例
    test_text = """
    第155章 数据交易的'后门'！被激活的'审查'病毒！
    
    伴随着档案管理员那郑重其事的声音落下，一场横跨宇宙文明维度的奇特交易正式生效。
    只见那由无数书页与数据流构成的人形轮廓轻轻一挥手，整个概念垃圾星都仿佛活了过来。
    """
    
    # 测试原有检测器
    print("=== 原有检测器结果 ===")
    checker = AIDensityChecker()
    result = checker.check_density(test_text)
    
    print(f"AI浓度分数: {result['ai_density_score']:.1f}")
    print(f"评估: {result['assessment']}")
    print("建议:")
    for suggestion in result['suggestions']:
        print(f"- {suggestion}")
    
    # 测试增强版检测器
    print("\n=== 增强版检测器结果 ===")
    enhanced_result = check_enhanced_ai_density(test_text)
    
    print(f"总体AI分数: {enhanced_result['total_score']:.1f}")
    print("各维度分数:")
    for dim, score in enhanced_result['dimension_scores'].items():
        print(f"- {dim}: {score:.1f}")
    
    print("\n朱雀AI检测分析:")
    zhuque = enhanced_result['zhuque_analysis']
    print(f"- 风险分数: {zhuque['zhuque_risk_score']:.1f}")
    print(f"- 高风险特征: {zhuque['high_risk_features']}")