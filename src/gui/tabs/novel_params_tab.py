"""Tab2: 小说参数配置 — 编辑 config.json 中的小说相关参数"""
import json
import logging
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QTextEdit,
    QComboBox, QPushButton, QScrollArea, QListWidget, QFileDialog, QMessageBox,
    QLabel,
)
from PySide6.QtCore import Qt, QEvent

from ..utils.config_io import load_config, save_config
from ..workers.writing_guide_worker import WritingGuideWorker
from ..widgets.resizable_text_edit import ResizableTextEdit


_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 辅助：创建固定行高的 QTextEdit
# ---------------------------------------------------------------------------
def _make_text_edit(rows: int = 3) -> QTextEdit:
    """创建支持拖拽调整高度的 QTextEdit，宽度自适应"""
    te = ResizableTextEdit()
    line_h = te.fontMetrics().lineSpacing()
    te.setMinimumHeight(line_h * rows + 16)
    te.setAcceptRichText(False)
    return te


def _expanding_form(parent=None) -> QFormLayout:
    """创建字段自动撑满宽度的 QFormLayout"""
    form = QFormLayout(parent)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    return form


# ---------------------------------------------------------------------------
# 辅助：安全取嵌套字典值
# ---------------------------------------------------------------------------
def _g(d: dict, *keys, default=""):
    """安全地从嵌套字典中取值"""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
    return cur if cur is not None else default


class NovelParamsTab(QWidget):
    """小说参数 Tab"""

    def __init__(self, config_path: str, env_path: str = ""):
        super().__init__()
        self._config_path = config_path
        self._env_path = env_path or os.path.join(
            os.path.dirname(config_path), ".env")
        self._guide_worker: WritingGuideWorker | None = None
        self._init_ui()
        self._load_from_file(silent=True)

    # ======================================================================
    # UI 构建
    # ======================================================================
    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        # 滚动区域包裹所有内容
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(16)

        self._build_basic_info()
        self._build_writing_guide()
        self._build_generation_config()
        self._build_kb_config()
        self._build_imitation_config()
        self._build_output_config()
        self._layout.addStretch()

        scroll.setWidget(container)
        root_layout.addWidget(scroll)

        # 底部按钮栏
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(16, 10, 16, 12)
        self._btn_new = QPushButton(self.tr("新建配置"))
        self._btn_new.clicked.connect(self._new_config)
        btn_bar.addWidget(self._btn_new)
        btn_bar.addStretch()
        self._btn_load = QPushButton(self.tr("加载配置"))
        self._btn_save = QPushButton(self.tr("保存配置"))
        self._btn_save.setProperty("cssClass", "primary")
        self._btn_load.clicked.connect(self._load_from_file)
        self._btn_save.clicked.connect(self._save_to_file)
        btn_bar.addWidget(self._btn_load)
        btn_bar.addWidget(self._btn_save)
        root_layout.addLayout(btn_bar)

    # ------------------------------------------------------------------
    # Section 1: 基本信息
    # ------------------------------------------------------------------
    def _build_basic_info(self):
        grp = QGroupBox(self.tr("基本信息"))
        form = _expanding_form(grp)

        self._le_title = QLineEdit()
        self._le_type = QLineEdit()
        self._le_theme = QLineEdit()
        self._le_style = QLineEdit()

        self._sp_chapters = QSpinBox()
        self._sp_chapters.setRange(1, 9999)
        self._sp_chapters.valueChanged.connect(self._on_chapters_changed)

        self._sp_chapter_len = QSpinBox()
        self._sp_chapter_len.setRange(500, 50000)
        self._sp_chapter_len.setSingleStep(500)

        form.addRow(self.tr("标题"), self._le_title)
        form.addRow(self.tr("类型"), self._le_type)
        form.addRow(self.tr("主题"), self._le_theme)
        form.addRow(self.tr("风格"), self._le_style)
        form.addRow(self.tr("目标章节数"), self._sp_chapters)
        form.addRow(self.tr("章节字数"), self._sp_chapter_len)

        self._layout.addWidget(grp)

    # ------------------------------------------------------------------
    # Section 2: 写作指南（可折叠）
    # ------------------------------------------------------------------
    def _build_writing_guide(self):
        grp = QGroupBox(self.tr("写作指南（展开编辑）"))
        grp.setCheckable(True)
        grp.setChecked(False)
        outer = QVBoxLayout(grp)

        # 自动生成区域:故事创意输入 + 生成按钮
        gen_bar = QHBoxLayout()
        self._le_story_idea = QLineEdit()
        self._le_story_idea.setPlaceholderText(self.tr("输入简短故事创意,如:废柴少年意外获得上古传承,踏上逆天修仙之路"))
        self._btn_gen_guide = QPushButton(self.tr("自动生成写作指南"))
        self._btn_gen_guide.setProperty("cssClass", "primary")
        self._btn_gen_guide.setToolTip(self.tr("根据故事创意和基本信息调用大纲模型自动生成"))
        self._btn_gen_guide.clicked.connect(self._on_generate_guide)
        gen_bar.addWidget(self._le_story_idea, stretch=1)
        gen_bar.addWidget(self._btn_gen_guide)
        outer.addLayout(gen_bar)

        # 角色生成数量与性别比例控制
        count_bar = QHBoxLayout()
        count_bar.addWidget(QLabel(self.tr("配角数")))
        self._sp_gen_supporting = QSpinBox()
        self._sp_gen_supporting.setRange(0, 30)
        self._sp_gen_supporting.setValue(6)
        self._sp_gen_supporting.setToolTip(self.tr("配角的目标总数；本次实际新增 = 目标 - 已有数量(下限 0)"))
        count_bar.addWidget(self._sp_gen_supporting)
        count_bar.addSpacing(12)
        count_bar.addWidget(QLabel(self.tr("反派数")))
        self._sp_gen_antagonists = QSpinBox()
        self._sp_gen_antagonists.setRange(0, 30)
        self._sp_gen_antagonists.setValue(4)
        self._sp_gen_antagonists.setToolTip(self.tr("反派的目标总数；本次实际新增 = 目标 - 已有数量(下限 0)"))
        count_bar.addWidget(self._sp_gen_antagonists)
        count_bar.addSpacing(12)
        count_bar.addWidget(QLabel(self.tr("女性比例")))
        self._dsb_gen_female_ratio = QDoubleSpinBox()
        self._dsb_gen_female_ratio.setRange(0.0, 1.0)
        self._dsb_gen_female_ratio.setSingleStep(0.1)
        self._dsb_gen_female_ratio.setDecimals(2)
        self._dsb_gen_female_ratio.setValue(0.3)
        count_bar.addWidget(self._dsb_gen_female_ratio)
        count_bar.addStretch()
        outer.addLayout(count_bar)

        # --- 世界观 ---
        wb_grp = QGroupBox(self.tr("世界观")); wb_grp.setProperty("cssClass", "inner")
        wb_form = _expanding_form(wb_grp)
        self._te_magic = _make_text_edit(4)
        self._te_social = _make_text_edit(4)
        self._te_bg = _make_text_edit(4)
        wb_form.addRow(self.tr("修炼体系"), self._te_magic)
        wb_form.addRow(self.tr("社会体系"), self._te_social)
        wb_form.addRow(self.tr("背景"), self._te_bg)
        outer.addWidget(wb_grp)

        # --- 主角设定 ---
        prot_grp = QGroupBox(self.tr("主角设定")); prot_grp.setProperty("cssClass", "inner")
        prot_form = _expanding_form(prot_grp)
        self._te_prot_bg = _make_text_edit(3)
        self._te_prot_personality = _make_text_edit(3)
        self._te_prot_growth = _make_text_edit(3)
        prot_form.addRow(self.tr("背景"), self._te_prot_bg)
        prot_form.addRow(self.tr("初始性格"), self._te_prot_personality)
        prot_form.addRow(self.tr("成长路线"), self._te_prot_growth)
        outer.addWidget(prot_grp)

        # --- 配角 & 反派（结构化列表 + 详情表单）---
        roles_grp = QGroupBox(self.tr("配角与反派")); roles_grp.setProperty("cssClass", "inner")
        roles_outer = QVBoxLayout(roles_grp)

        # 配角编辑器
        self._sup_data: list[dict] = []
        self._sup_updating = False
        sup_box = self._make_role_editor(
            title=self.tr("配角 (supporting_roles)"),
            data_attr="_sup_data",
            last_field_key="relationship",
            last_field_label=self.tr("与主角关系"),
            is_antagonist=False,
        )
        roles_outer.addWidget(sup_box)

        # 反派编辑器
        self._ant_data: list[dict] = []
        self._ant_updating = False
        ant_box = self._make_role_editor(
            title=self.tr("反派 (antagonists)"),
            data_attr="_ant_data",
            last_field_key="conflict_point",
            last_field_label=self.tr("冲突点"),
            is_antagonist=True,
        )
        roles_outer.addWidget(ant_box)

        outer.addWidget(roles_grp)

        # --- 剧情结构 ---
        plot_grp = QGroupBox(self.tr("剧情结构")); plot_grp.setProperty("cssClass", "inner")
        plot_form = _expanding_form(plot_grp)
        # 第一幕
        self._te_setup = _make_text_edit(3)
        self._te_inciting = _make_text_edit(3)
        self._te_fp1 = _make_text_edit(3)
        plot_form.addRow(self.tr("第一幕 - setup"), self._te_setup)
        plot_form.addRow(self.tr("第一幕 - inciting_incident"), self._te_inciting)
        plot_form.addRow(self.tr("第一幕 - first_plot_point"), self._te_fp1)
        # 第二幕
        self._te_rising = _make_text_edit(3)
        self._te_midpoint = _make_text_edit(3)
        self._te_complications = _make_text_edit(3)
        self._te_darkest = _make_text_edit(3)
        self._te_sp2 = _make_text_edit(3)
        plot_form.addRow(self.tr("第二幕 - rising_action"), self._te_rising)
        plot_form.addRow(self.tr("第二幕 - midpoint"), self._te_midpoint)
        plot_form.addRow(self.tr("第二幕 - complications"), self._te_complications)
        plot_form.addRow(self.tr("第二幕 - darkest_moment"), self._te_darkest)
        plot_form.addRow(self.tr("第二幕 - second_plot_point"), self._te_sp2)
        # 第三幕
        self._te_climax = _make_text_edit(3)
        self._te_resolution = _make_text_edit(3)
        self._te_denouement = _make_text_edit(3)
        plot_form.addRow(self.tr("第三幕 - climax"), self._te_climax)
        plot_form.addRow(self.tr("第三幕 - resolution"), self._te_resolution)
        plot_form.addRow(self.tr("第三幕 - denouement"), self._te_denouement)
        # 节奏锚点（三次灾难，对应 plot_structure.disasters）
        self._te_disaster_1 = _make_text_edit(2)
        self._te_disaster_1.setPlaceholderText(self.tr("约 25% 处：第一次灾难事件，主角首次面临生死考验"))
        self._te_disaster_2 = _make_text_edit(2)
        self._te_disaster_2.setPlaceholderText(self.tr("约 50% 处：第二次灾难事件，主角遭遇重大挫折或身份危机"))
        self._te_disaster_3 = _make_text_edit(2)
        self._te_disaster_3.setPlaceholderText(self.tr("约 75% 处：第三次灾难事件，主角必须直面远超自身的敌人"))
        plot_form.addRow(self.tr("节奏锚点 - 第一次灾难"), self._te_disaster_1)
        plot_form.addRow(self.tr("节奏锚点 - 第二次灾难"), self._te_disaster_2)
        plot_form.addRow(self.tr("节奏锚点 - 第三次灾难"), self._te_disaster_3)
        outer.addWidget(plot_grp)

        # --- 风格指南 ---
        style_grp = QGroupBox(self.tr("风格指南")); style_grp.setProperty("cssClass", "inner")
        style_form = _expanding_form(style_grp)
        self._te_tone = _make_text_edit(3)
        self._te_pacing = _make_text_edit(3)
        style_form.addRow(self.tr("tone(基调)"), self._te_tone)
        style_form.addRow(self.tr("pacing(节奏)"), self._te_pacing)

        # description_focus: 描写侧重点列表(至少 3 条)
        focus_wrapper = QWidget()
        focus_layout = QVBoxLayout(focus_wrapper)
        focus_layout.setContentsMargins(0, 0, 0, 0)
        focus_layout.setSpacing(4)
        focus_tip = QLabel(self.tr("至少 3 条，每条描述一个描写侧重点(战斗 / 世界观 / 人物等)"))
        focus_tip.setStyleSheet("color: gray; font-size: 11px;")
        focus_layout.addWidget(focus_tip)

        focus_row = QHBoxLayout()
        self._lw_desc_focus = QListWidget()
        self._lw_desc_focus.setMinimumHeight(80)
        self._lw_desc_focus.setMaximumHeight(140)
        self._lw_desc_focus.currentRowChanged.connect(self._on_focus_selected)
        focus_row.addWidget(self._lw_desc_focus, stretch=1)

        focus_btn_col = QVBoxLayout()
        btn_add_focus = QPushButton(self.tr("添加"))
        btn_del_focus = QPushButton(self.tr("删除"))
        btn_up_focus = QPushButton(self.tr("上移"))
        btn_down_focus = QPushButton(self.tr("下移"))
        for b in (btn_add_focus, btn_del_focus, btn_up_focus, btn_down_focus):
            b.setMinimumWidth(60)
        btn_add_focus.clicked.connect(self._add_desc_focus)
        btn_del_focus.clicked.connect(self._del_desc_focus)
        btn_up_focus.clicked.connect(lambda: self._move_desc_focus(-1))
        btn_down_focus.clicked.connect(lambda: self._move_desc_focus(1))
        focus_btn_col.addWidget(btn_add_focus)
        focus_btn_col.addWidget(btn_del_focus)
        focus_btn_col.addWidget(btn_up_focus)
        focus_btn_col.addWidget(btn_down_focus)
        focus_btn_col.addStretch()
        focus_row.addLayout(focus_btn_col)
        focus_layout.addLayout(focus_row)

        self._te_desc_focus_detail = _make_text_edit(3)
        self._te_desc_focus_detail.setPlaceholderText(self.tr("选中左侧条目后编辑描写侧重点内容"))
        self._te_desc_focus_detail.textChanged.connect(self._on_focus_detail_changed)
        focus_layout.addWidget(self._te_desc_focus_detail)

        style_form.addRow(self.tr("描写重点 (description_focus)"), focus_wrapper)

        # 内部数据列表 + 更新锁
        self._desc_focus_data: list[str] = []
        self._focus_updating = False

        outer.addWidget(style_grp)

        self._layout.addWidget(grp)

    # ------------------------------------------------------------------
    # 角色编辑器（配角 / 反派通用）
    # ------------------------------------------------------------------
    def _make_role_editor(
        self,
        title: str,
        data_attr: str,
        last_field_key: str,
        last_field_label: str,
        is_antagonist: bool,
    ) -> QGroupBox:
        """创建「列表 + 详情表单」形式的角色编辑器

        参数：
            data_attr: 实例上的数据列表属性名（_sup_data / _ant_data）
            last_field_key: 独有字段的 JSON key（relationship / conflict_point）
            last_field_label: 独有字段的 UI 标签
            is_antagonist: 是否反派（用于保存时区分）
        """
        grp = QGroupBox(title)
        outer_v = QVBoxLayout(grp)

        # 上：列表 + 操作按钮
        list_row = QHBoxLayout()
        lw = QListWidget()
        lw.setMinimumHeight(100)
        lw.setMaximumHeight(160)
        list_row.addWidget(lw, stretch=1)

        btn_col = QVBoxLayout()
        btn_add = QPushButton(self.tr("添加"))
        btn_del = QPushButton(self.tr("删除"))
        btn_up = QPushButton(self.tr("上移"))
        btn_down = QPushButton(self.tr("下移"))
        for b in (btn_add, btn_del, btn_up, btn_down):
            b.setMinimumWidth(60)
        btn_col.addWidget(btn_add)
        btn_col.addWidget(btn_del)
        btn_col.addWidget(btn_up)
        btn_col.addWidget(btn_down)
        btn_col.addStretch()
        list_row.addLayout(btn_col)
        outer_v.addLayout(list_row)

        # 下：详情表单
        detail = QGroupBox(self.tr("角色详情"))
        form = _expanding_form(detail)
        le_name = QLineEdit()
        le_name.setPlaceholderText(self.tr("角色名称（列表仅显示此字段）"))
        cb_gender = QComboBox()
        cb_gender.addItems([self.tr("未指定"), self.tr("男"), self.tr("女"), self.tr("其他")])
        le_role_type = QLineEdit()
        le_role_type.setPlaceholderText(self.tr("角色类型，如 导师/亲人、初期反派 等"))
        te_personality = _make_text_edit(3)
        te_personality.setPlaceholderText(self.tr("性格描述与背景"))
        te_last = _make_text_edit(2)
        te_last.setPlaceholderText(
            self.tr("与主角的冲突点") if is_antagonist else self.tr("与主角的关系")
        )
        form.addRow(self.tr("名称"), le_name)
        form.addRow(self.tr("性别"), cb_gender)
        form.addRow(self.tr("角色类型"), le_role_type)
        form.addRow(self.tr("性格"), te_personality)
        form.addRow(last_field_label, te_last)
        outer_v.addWidget(detail)

        # 保存控件引用（按 data_attr 前缀区分）
        prefix = "_sup" if data_attr == "_sup_data" else "_ant"
        setattr(self, f"{prefix}_lw", lw)
        setattr(self, f"{prefix}_le_name", le_name)
        setattr(self, f"{prefix}_cb_gender", cb_gender)
        setattr(self, f"{prefix}_le_role_type", le_role_type)
        setattr(self, f"{prefix}_te_personality", te_personality)
        setattr(self, f"{prefix}_te_last", te_last)
        setattr(self, f"{prefix}_last_key", last_field_key)

        # 绑定事件
        lw.currentRowChanged.connect(
            lambda row, a=data_attr: self._on_role_selected(row, a)
        )
        btn_add.clicked.connect(lambda: self._add_role(data_attr))
        btn_del.clicked.connect(lambda: self._del_role(data_attr))
        btn_up.clicked.connect(lambda: self._move_role(data_attr, -1))
        btn_down.clicked.connect(lambda: self._move_role(data_attr, 1))

        le_name.textChanged.connect(lambda _: self._on_role_detail_changed(data_attr))
        cb_gender.currentIndexChanged.connect(lambda _: self._on_role_detail_changed(data_attr))
        le_role_type.textChanged.connect(lambda _: self._on_role_detail_changed(data_attr))
        te_personality.textChanged.connect(lambda: self._on_role_detail_changed(data_attr))
        te_last.textChanged.connect(lambda: self._on_role_detail_changed(data_attr))

        return grp

    def _role_widgets(self, data_attr: str):
        """根据 data_attr 返回控件元组"""
        prefix = "_sup" if data_attr == "_sup_data" else "_ant"
        return (
            getattr(self, f"{prefix}_lw"),
            getattr(self, f"{prefix}_le_name"),
            getattr(self, f"{prefix}_cb_gender"),
            getattr(self, f"{prefix}_le_role_type"),
            getattr(self, f"{prefix}_te_personality"),
            getattr(self, f"{prefix}_te_last"),
            getattr(self, f"{prefix}_last_key"),
        )

    def _set_role_updating(self, data_attr: str, value: bool):
        attr = "_sup_updating" if data_attr == "_sup_data" else "_ant_updating"
        setattr(self, attr, value)

    def _get_role_updating(self, data_attr: str) -> bool:
        attr = "_sup_updating" if data_attr == "_sup_data" else "_ant_updating"
        return getattr(self, attr, False)

    def _refresh_role_list(self, data_attr: str):
        data = getattr(self, data_attr)
        lw, *_ = self._role_widgets(data_attr)
        lw.clear()
        for item in data:
            display = item.get("name") or item.get("role_type") or self.tr("(未命名)")
            lw.addItem(str(display))

    def _add_role(self, data_attr: str):
        data = getattr(self, data_attr)
        new_item = {
            "name": "",
            "gender": "",
            "role_type": "",
            "personality": "",
        }
        # 末字段占位
        _, _, _, _, _, _, last_key = self._role_widgets(data_attr)
        new_item[last_key] = ""
        data.append(new_item)
        self._refresh_role_list(data_attr)
        lw, *_ = self._role_widgets(data_attr)
        lw.setCurrentRow(len(data) - 1)

    def _del_role(self, data_attr: str):
        data = getattr(self, data_attr)
        lw, *_ = self._role_widgets(data_attr)
        row = lw.currentRow()
        if 0 <= row < len(data):
            data.pop(row)
            self._refresh_role_list(data_attr)
            if data:
                lw.setCurrentRow(min(row, len(data) - 1))
            else:
                self._clear_role_detail(data_attr)

    def _move_role(self, data_attr: str, delta: int):
        data = getattr(self, data_attr)
        lw, *_ = self._role_widgets(data_attr)
        row = lw.currentRow()
        new_row = row + delta
        if 0 <= row < len(data) and 0 <= new_row < len(data):
            data[row], data[new_row] = data[new_row], data[row]
            self._refresh_role_list(data_attr)
            lw.setCurrentRow(new_row)

    def _clear_role_detail(self, data_attr: str):
        self._set_role_updating(data_attr, True)
        _, le_name, cb_gender, le_role_type, te_personality, te_last, _ = self._role_widgets(data_attr)
        le_name.clear()
        cb_gender.setCurrentIndex(0)
        le_role_type.clear()
        te_personality.clear()
        te_last.clear()
        self._set_role_updating(data_attr, False)

    def _on_role_selected(self, row: int, data_attr: str):
        data = getattr(self, data_attr)
        _, le_name, cb_gender, le_role_type, te_personality, te_last, last_key = self._role_widgets(data_attr)
        self._set_role_updating(data_attr, True)
        if 0 <= row < len(data):
            item = data[row]
            le_name.setText(str(item.get("name", "")))
            gender = str(item.get("gender", ""))
            gender_map = {"": 0, "男": 1, "女": 2, "其他": 3}
            cb_gender.setCurrentIndex(gender_map.get(gender, 0))
            le_role_type.setText(str(item.get("role_type", "")))
            te_personality.setPlainText(str(item.get("personality", "")))
            te_last.setPlainText(str(item.get(last_key, "")))
        else:
            le_name.clear()
            cb_gender.setCurrentIndex(0)
            le_role_type.clear()
            te_personality.clear()
            te_last.clear()
        self._set_role_updating(data_attr, False)

    def _on_role_detail_changed(self, data_attr: str):
        if self._get_role_updating(data_attr):
            return
        data = getattr(self, data_attr)
        lw, le_name, cb_gender, le_role_type, te_personality, te_last, last_key = self._role_widgets(data_attr)
        row = lw.currentRow()
        if not (0 <= row < len(data)):
            return
        gender_text = cb_gender.currentText()
        if gender_text == self.tr("未指定"):
            gender_text = ""
        data[row] = {
            "name": le_name.text(),
            "gender": gender_text,
            "role_type": le_role_type.text(),
            "personality": te_personality.toPlainText(),
            last_key: te_last.toPlainText(),
        }
        # 同步列表显示
        display = data[row].get("name") or data[row].get("role_type") or self.tr("(未命名)")
        item = lw.item(row)
        if item:
            item.setText(str(display))

    def _load_roles(self, data_attr: str, raw):
        """将 raw(list[dict]) 装载到数据模型中，并刷新 UI

        兼容旧配置：若 dict 缺少 name 字段，尝试从 personality 中
        提取冒号前的名字（如 "司婆婆：残老村的裁缝..." → name="司婆婆"）。
        """
        normalized: list[dict] = []
        if isinstance(raw, list):
            for it in raw:
                if isinstance(it, dict):
                    d = dict(it)
                    # 旧配置兼容：从 personality 提取角色名
                    if not d.get("name"):
                        personality = str(d.get("personality", ""))
                        for sep in ("：", ":"):
                            if sep in personality:
                                candidate = personality.split(sep, 1)[0].strip()
                                if 1 <= len(candidate) <= 10:
                                    d["name"] = candidate
                                break
                    normalized.append(d)
                elif isinstance(it, str):
                    normalized.append({"name": it})
        setattr(self, data_attr, normalized)
        self._refresh_role_list(data_attr)
        lw, *_ = self._role_widgets(data_attr)
        if normalized:
            lw.setCurrentRow(0)
        else:
            self._clear_role_detail(data_attr)

    @staticmethod
    def _normalize_role(it) -> dict | None:
        """将单个角色 raw 项规范化为 dict（含 name 推断）；非法则返回 None"""
        if isinstance(it, dict):
            d = dict(it)
            if not d.get("name"):
                personality = str(d.get("personality", ""))
                for sep in ("：", ":"):
                    if sep in personality:
                        candidate = personality.split(sep, 1)[0].strip()
                        if 1 <= len(candidate) <= 10:
                            d["name"] = candidate
                        break
            return d
        if isinstance(it, str):
            name = it.strip()
            return {"name": name} if name else None
        return None

    def _merge_roles(self, data_attr: str, raw):
        """增补模式：保留已有角色，按 name 去重追加新角色

        策略：
        - 已有列表完整保留
        - 新生成项中 name 与已有项重复则跳过（首次出现优先）
        - 新生成项无 name 时也追加（无法去重判定）
        """
        existing: list[dict] = list(getattr(self, data_attr, []) or [])
        existing_names = {
            str(r.get("name", "")).strip()
            for r in existing
            if isinstance(r, dict)
        }
        existing_names.discard("")

        appended: list[dict] = []
        if isinstance(raw, list):
            for it in raw:
                d = self._normalize_role(it)
                if d is None:
                    continue
                name = str(d.get("name", "")).strip()
                if name and name in existing_names:
                    continue
                if name:
                    existing_names.add(name)
                appended.append(d)

        merged = existing + appended
        setattr(self, data_attr, merged)
        self._refresh_role_list(data_attr)
        lw, *_ = self._role_widgets(data_attr)
        if merged:
            # 优先选中第一条新追加项，便于用户立刻审阅；若无追加则保持现有选择
            if appended:
                lw.setCurrentRow(len(existing))
            elif lw.currentRow() < 0:
                lw.setCurrentRow(0)
        else:
            self._clear_role_detail(data_attr)

    @staticmethod
    def _set_text_if_empty(widget, value) -> bool:
        """增补模式：仅当 widget 当前为空白时才填入新值

        返回是否实际写入（用于统计）。
        """
        try:
            current = widget.toPlainText()
        except AttributeError:
            current = ""
        if current.strip():
            return False
        text = "" if value is None else str(value)
        if not text.strip():
            return False
        widget.setPlainText(text)
        return True

    # ------------------------------------------------------------------
    # Section 3: 生成配置
    # ------------------------------------------------------------------
    def _build_generation_config(self):
        grp = QGroupBox(self.tr("生成配置"))
        outer = QVBoxLayout(grp)

        # 大纲生成参数
        o_grp = QGroupBox(self.tr("大纲生成"))
        o_form = _expanding_form(o_grp)

        self._sp_batch_size = QSpinBox()
        self._sp_batch_size.setRange(1, 50)
        self._sp_batch_size.setToolTip(self.tr("每次 API 调用生成的章节数"))
        o_form.addRow(self.tr("每批生成章节数"), self._sp_batch_size)

        self._sp_outline_batch = QSpinBox()
        self._sp_outline_batch.setRange(10, 500)
        self._sp_outline_batch.setSingleStep(10)
        self._sp_outline_batch.setToolTip(self.tr("主批次大小,超长大纲(400+章)建议设为 200"))
        o_form.addRow(self.tr("主批次大小"), self._sp_outline_batch)

        self._sp_context_chapters = QSpinBox()
        self._sp_context_chapters.setRange(3, 1000)
        self._sp_context_chapters.setToolTip(self.tr("生成大纲时参考的前文章节数,章节越多上下文越丰富但 token 消耗更大"))
        o_form.addRow(self.tr("上下文章节数"), self._sp_context_chapters)

        self._sp_detail_chapters = QSpinBox()
        self._sp_detail_chapters.setRange(1, 200)
        self._sp_detail_chapters.setToolTip(self.tr("在上下文中详细展示的最近章节数"))
        o_form.addRow(self.tr("详细展示章节数"), self._sp_detail_chapters)

        self._sp_chapters_per_arc = QSpinBox()
        self._sp_chapters_per_arc.setRange(0, 200)
        self._sp_chapters_per_arc.setSingleStep(5)
        self._sp_chapters_per_arc.setToolTip(self.tr("每卷章节数，用于卷内情绪节奏控制（螺旋上升模型：成长→挫折→绝境→爆发→跌落→新局）。设为 0 则禁用"))
        o_form.addRow(self.tr("每卷章节数(情绪节奏)"), self._sp_chapters_per_arc)

        outer.addWidget(o_grp)

        # 验证开关
        v_grp = QGroupBox(self.tr("验证"))
        v_lay = QHBoxLayout(v_grp)
        self._cb_logic = QCheckBox(self.tr("逻辑检查"))
        self._cb_consistency = QCheckBox(self.tr("一致性检查"))
        self._cb_duplicates = QCheckBox(self.tr("重复检查"))
        v_lay.addWidget(self._cb_logic)
        v_lay.addWidget(self._cb_consistency)
        v_lay.addWidget(self._cb_duplicates)
        outer.addWidget(v_grp)

        # 人性化参数
        h_grp = QGroupBox(self.tr("人性化参数"))
        h_form = _expanding_form(h_grp)

        self._dsb_temp = QDoubleSpinBox()
        self._dsb_temp.setRange(0.0, 2.0)
        self._dsb_temp.setSingleStep(0.1)
        self._dsb_temp.setDecimals(2)

        self._dsb_top_p = QDoubleSpinBox()
        self._dsb_top_p.setRange(0.0, 1.0)
        self._dsb_top_p.setSingleStep(0.05)
        self._dsb_top_p.setDecimals(2)

        self._dsb_dialogue = QDoubleSpinBox()
        self._dsb_dialogue.setRange(0.0, 1.0)
        self._dsb_dialogue.setSingleStep(0.05)
        self._dsb_dialogue.setDecimals(2)

        self._cb_desc_simp = QCheckBox(self.tr("描写简化"))
        self._cb_emotion = QCheckBox(self.tr("情感增强"))
        self._cb_humanizer_zh = QCheckBox(self.tr("Humanizer-zh 增强"))
        self._cb_humanizer_zh.setToolTip(self.tr("启用 Humanizer-zh 人性化增强规则,降低 AI 写作痕迹"))

        h_form.addRow("temperature", self._dsb_temp)
        h_form.addRow("top_p", self._dsb_top_p)
        h_form.addRow("dialogue_ratio", self._dsb_dialogue)
        h_form.addRow("", self._cb_desc_simp)
        h_form.addRow("", self._cb_emotion)
        h_form.addRow("", self._cb_humanizer_zh)
        outer.addWidget(h_grp)

        self._layout.addWidget(grp)

    # ------------------------------------------------------------------
    # Section 4: 知识库配置
    # ------------------------------------------------------------------
    def _build_kb_config(self):
        grp = QGroupBox(self.tr("知识库配置"))
        form = _expanding_form(grp)

        # 参考文件列表
        self._lw_refs = QListWidget()
        self._lw_refs.setMaximumHeight(100)
        btn_row = QHBoxLayout()
        btn_add = QPushButton(self.tr("添加文件"))
        btn_del = QPushButton(self.tr("删除选中"))
        btn_add.clicked.connect(self._add_ref_file)
        btn_del.clicked.connect(self._del_ref_file)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()

        ref_box = QVBoxLayout()
        ref_box.addWidget(self._lw_refs)
        ref_box.addLayout(btn_row)
        ref_wrapper = QWidget()
        ref_wrapper.setLayout(ref_box)
        form.addRow(self.tr("参考文件"), ref_wrapper)

        self._sp_chunk = QSpinBox()
        self._sp_chunk.setRange(100, 10000)
        self._sp_chunk.setSingleStep(100)
        self._sp_overlap = QSpinBox()
        self._sp_overlap.setRange(0, 5000)
        self._sp_overlap.setSingleStep(50)
        form.addRow(self.tr("分块大小"), self._sp_chunk)
        form.addRow(self.tr("分块重叠"), self._sp_overlap)

        self._layout.addWidget(grp)

    # ------------------------------------------------------------------
    # Section 5: 仿写配置（可折叠）
    # ------------------------------------------------------------------
    def _build_imitation_config(self):
        grp = QGroupBox(self.tr("仿写配置(展开编辑)"))
        grp.setCheckable(True)
        grp.setChecked(False)
        outer = QVBoxLayout(grp)

        # --- 自动仿写 ---
        auto_grp = QGroupBox(self.tr("自动仿写"))
        auto_form = _expanding_form(auto_grp)

        self._cb_imit_enabled = QCheckBox(self.tr("启用仿写功能"))
        auto_form.addRow("", self._cb_imit_enabled)

        self._cb_auto_imit = QCheckBox(self.tr("自动仿写(生成后自动执行)"))
        auto_form.addRow("", self._cb_auto_imit)

        self._cb_trigger_all = QCheckBox(self.tr("对所有章节触发"))
        auto_form.addRow("", self._cb_trigger_all)

        self._le_default_style = QComboBox()
        auto_form.addRow(self.tr("默认风格"), self._le_default_style)

        self._le_output_suffix = QLineEdit()
        self._le_output_suffix.setPlaceholderText("_imitated")
        auto_form.addRow(self.tr("输出后缀"), self._le_output_suffix)

        self._cb_backup_original = QCheckBox(self.tr("备份原文"))
        auto_form.addRow("", self._cb_backup_original)

        outer.addWidget(auto_grp)

        # --- 风格源列表(可视化编辑)---
        style_grp = QGroupBox(self.tr("风格源列表"))
        style_outer = QVBoxLayout(style_grp)

        # 上半部分:列表 + 按钮
        list_row = QHBoxLayout()
        self._lw_styles = QListWidget()
        self._lw_styles.setMaximumHeight(120)
        self._lw_styles.currentRowChanged.connect(self._on_style_selected)
        list_row.addWidget(self._lw_styles, stretch=1)

        btn_col = QVBoxLayout()
        btn_add_style = QPushButton(self.tr("添加"))
        btn_del_style = QPushButton(self.tr("删除"))
        btn_add_style.setMinimumWidth(60)  # 改为最小宽度,允许自动扩展
        btn_del_style.setMinimumWidth(60)  # 改为最小宽度,允许自动扩展
        btn_add_style.clicked.connect(self._add_style_source)
        btn_del_style.clicked.connect(self._del_style_source)
        btn_col.addWidget(btn_add_style)
        btn_col.addWidget(btn_del_style)
        btn_col.addStretch()
        list_row.addLayout(btn_col)
        style_outer.addLayout(list_row)

        # 下半部分:选中风格的详细编辑
        detail_grp = QGroupBox(self.tr("风格详情"))
        detail_form = _expanding_form(detail_grp)
        self._le_ss_name = QLineEdit()
        self._le_ss_name.setPlaceholderText(self.tr("风格名称"))
        self._le_ss_name.textChanged.connect(self._on_style_detail_changed)
        detail_form.addRow(self.tr("名称"), self._le_ss_name)

        fp_row = QHBoxLayout()
        self._le_ss_path = QLineEdit()
        self._le_ss_path.setPlaceholderText("data/style_sources/xxx.txt")
        self._le_ss_path.textChanged.connect(self._on_style_detail_changed)
        btn_browse_ss = QPushButton(self.tr("浏览"))
        btn_browse_ss.clicked.connect(self._browse_style_file)
        fp_row.addWidget(self._le_ss_path)
        fp_row.addWidget(btn_browse_ss)
        fp_wrapper = QWidget()
        fp_wrapper.setLayout(fp_row)
        detail_form.addRow(self.tr("参考文件"), fp_wrapper)

        self._le_ss_desc = QLineEdit()
        self._le_ss_desc.setPlaceholderText(self.tr("风格描述"))
        self._le_ss_desc.textChanged.connect(self._on_style_detail_changed)
        detail_form.addRow(self.tr("描述"), self._le_ss_desc)

        self._le_ss_prompt = QLineEdit()
        self._le_ss_prompt.setPlaceholderText(self.tr("额外仿写提示词"))
        self._le_ss_prompt.textChanged.connect(self._on_style_detail_changed)
        detail_form.addRow(self.tr("额外提示词"), self._le_ss_prompt)

        style_outer.addWidget(detail_grp)
        outer.addWidget(style_grp)

        # 内部数据:风格源列表
        self._style_sources_data: list[dict] = []
        self._style_updating = False  # 防止循环触发

        # --- 手动仿写 ---
        manual_grp = QGroupBox(self.tr("手动仿写"))
        manual_form = _expanding_form(manual_grp)

        self._cb_manual_imit = QCheckBox(self.tr("启用手动仿写"))
        manual_form.addRow("", self._cb_manual_imit)

        row = QHBoxLayout()
        self._le_imit_output_dir = QLineEdit()
        self._le_imit_output_dir.setPlaceholderText("data/imitation_output")
        btn_browse = QPushButton(self.tr("浏览"))
        btn_browse.clicked.connect(self._browse_imit_output_dir)
        row.addWidget(self._le_imit_output_dir)
        row.addWidget(btn_browse)
        wrapper = QWidget()
        wrapper.setLayout(row)
        manual_form.addRow(self.tr("输出目录"), wrapper)

        outer.addWidget(manual_grp)

        # --- 质量控制 ---
        qc_grp = QGroupBox(self.tr("质量控制"))
        qc_form = _expanding_form(qc_grp)

        self._dsb_min_similarity = QDoubleSpinBox()
        self._dsb_min_similarity.setRange(0.0, 1.0)
        self._dsb_min_similarity.setSingleStep(0.05)
        self._dsb_min_similarity.setDecimals(2)
        qc_form.addRow(self.tr("最低风格相似度"), self._dsb_min_similarity)

        self._sp_imit_retries = QSpinBox()
        self._sp_imit_retries.setRange(1, 10)
        qc_form.addRow(self.tr("最大重试次数"), self._sp_imit_retries)

        self._cb_content_check = QCheckBox(self.tr("内容保留检查"))
        self._cb_style_check = QCheckBox(self.tr("风格一致性检查"))
        qc_form.addRow("", self._cb_content_check)
        qc_form.addRow("", self._cb_style_check)

        outer.addWidget(qc_grp)
        self._layout.addWidget(grp)

    def _browse_imit_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, self.tr("选择仿写输出目录"))
        if d:
            self._le_imit_output_dir.setText(d)

    # --- 风格源列表交互 ---

    def _sync_style_combo(self):
        """同步风格名称到默认风格下拉框"""
        current = self._le_default_style.currentText()
        self._le_default_style.clear()
        for item in self._style_sources_data:
            name = item.get("name", "")
            if name:
                self._le_default_style.addItem(name)
        idx = self._le_default_style.findText(current)
        if idx >= 0:
            self._le_default_style.setCurrentIndex(idx)

    def _refresh_style_list(self):
        """刷新 QListWidget 显示"""
        self._lw_styles.clear()
        for item in self._style_sources_data:
            self._lw_styles.addItem(item.get("name", self.tr("(未命名)")))
        self._sync_style_combo()

    def _add_style_source(self):
        """添加一个新的空风格源"""
        new_item = {
            "name": self.tr("新风格{0}").format(len(self._style_sources_data) + 1),
            "file_path": "",
            "description": "",
            "extra_prompt": "",
        }
        self._style_sources_data.append(new_item)
        self._refresh_style_list()
        self._lw_styles.setCurrentRow(len(self._style_sources_data) - 1)

    def _del_style_source(self):
        """删除选中的风格源"""
        row = self._lw_styles.currentRow()
        if 0 <= row < len(self._style_sources_data):
            self._style_sources_data.pop(row)
            self._refresh_style_list()
            if self._style_sources_data:
                self._lw_styles.setCurrentRow(min(row, len(self._style_sources_data) - 1))
            else:
                self._clear_style_detail()

    def _on_style_selected(self, row: int):
        """列表选中项变化时，填充详情编辑区"""
        self._style_updating = True
        if 0 <= row < len(self._style_sources_data):
            item = self._style_sources_data[row]
            self._le_ss_name.setText(item.get("name", ""))
            self._le_ss_path.setText(item.get("file_path", ""))
            self._le_ss_desc.setText(item.get("description", ""))
            self._le_ss_prompt.setText(item.get("extra_prompt", ""))
        else:
            self._clear_style_detail()
        self._style_updating = False

    def _clear_style_detail(self):
        self._le_ss_name.clear()
        self._le_ss_path.clear()
        self._le_ss_desc.clear()
        self._le_ss_prompt.clear()

    def _on_style_detail_changed(self):
        """详情编辑区内容变化时，回写到数据列表"""
        if self._style_updating:
            return
        row = self._lw_styles.currentRow()
        if 0 <= row < len(self._style_sources_data):
            self._style_sources_data[row] = {
                "name": self._le_ss_name.text(),
                "file_path": self._le_ss_path.text(),
                "description": self._le_ss_desc.text(),
                "extra_prompt": self._le_ss_prompt.text(),
            }
            # 同步列表显示名称
            item = self._lw_styles.item(row)
            if item:
                item.setText(self._le_ss_name.text() or self.tr("(未命名)"))
            self._sync_style_combo()

    def _browse_style_file(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr("选择风格参考文件"), "", self.tr("文本文件 (*.txt);;所有文件 (*)"))
        if path:
            self._le_ss_path.setText(path)

    # --- 描写重点列表交互 ---
    def _refresh_desc_focus_list(self):
        """刷新描写重点 QListWidget 显示"""
        self._lw_desc_focus.clear()
        for item in self._desc_focus_data:
            text = item if isinstance(item, str) else str(item)
            preview = (text[:30] + "…") if len(text) > 30 else text
            self._lw_desc_focus.addItem(preview or self.tr("(空)"))

    def _add_desc_focus(self):
        """追加一条空的描写重点"""
        self._desc_focus_data.append("")
        self._refresh_desc_focus_list()
        self._lw_desc_focus.setCurrentRow(len(self._desc_focus_data) - 1)

    def _del_desc_focus(self):
        """删除选中的描写重点"""
        row = self._lw_desc_focus.currentRow()
        if 0 <= row < len(self._desc_focus_data):
            self._desc_focus_data.pop(row)
            self._refresh_desc_focus_list()
            if self._desc_focus_data:
                self._lw_desc_focus.setCurrentRow(min(row, len(self._desc_focus_data) - 1))
            else:
                self._focus_updating = True
                self._te_desc_focus_detail.clear()
                self._focus_updating = False

    def _move_desc_focus(self, delta: int):
        """上移/下移选中的描写重点"""
        row = self._lw_desc_focus.currentRow()
        new_row = row + delta
        if 0 <= row < len(self._desc_focus_data) and 0 <= new_row < len(self._desc_focus_data):
            self._desc_focus_data[row], self._desc_focus_data[new_row] = (
                self._desc_focus_data[new_row],
                self._desc_focus_data[row],
            )
            self._refresh_desc_focus_list()
            self._lw_desc_focus.setCurrentRow(new_row)

    def _on_focus_selected(self, row: int):
        """列表选中变化时，把详情写到编辑框"""
        self._focus_updating = True
        if 0 <= row < len(self._desc_focus_data):
            self._te_desc_focus_detail.setPlainText(str(self._desc_focus_data[row]))
        else:
            self._te_desc_focus_detail.clear()
        self._focus_updating = False

    def _on_focus_detail_changed(self):
        """编辑框变化回写到数据列表"""
        if self._focus_updating:
            return
        row = self._lw_desc_focus.currentRow()
        if 0 <= row < len(self._desc_focus_data):
            self._desc_focus_data[row] = self._te_desc_focus_detail.toPlainText()
            text = self._desc_focus_data[row]
            preview = (text[:30] + "…") if len(text) > 30 else text
            item = self._lw_desc_focus.item(row)
            if item:
                item.setText(preview or self.tr("(空)"))

    # ------------------------------------------------------------------
    # Section 6: 输出配置
    # ------------------------------------------------------------------
    def _build_output_config(self):
        grp = QGroupBox(self.tr("输出配置"))
        form = _expanding_form(grp)

        row = QHBoxLayout()
        self._le_output_dir = QLineEdit()
        btn_browse = QPushButton(self.tr("浏览"))
        btn_browse.clicked.connect(self._browse_output_dir)
        row.addWidget(self._le_output_dir)
        row.addWidget(btn_browse)
        dir_wrapper = QWidget()
        dir_wrapper.setLayout(row)
        form.addRow(self.tr("输出目录"), dir_wrapper)

        self._layout.addWidget(grp)

    # ======================================================================
    # 文件对话框回调
    # ======================================================================
    def _add_ref_file(self):
        paths, _ = QFileDialog.getOpenFileNames(self, self.tr("选择参考文件"))
        for p in paths:
            if not self._lw_refs.findItems(p, Qt.MatchExactly):
                self._lw_refs.addItem(p)

    def _del_ref_file(self):
        for item in self._lw_refs.selectedItems():
            self._lw_refs.takeItem(self._lw_refs.row(item))

    def _browse_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, self.tr("选择输出目录"))
        if d:
            self._le_output_dir.setText(d)

    # ======================================================================
    # 新建配置（备份现有 + 从模板创建空白）
    # ======================================================================
    def _new_config(self):
        """备份当前 config.json,然后从 config.json.example 创建空白配置"""
        import shutil
        from datetime import datetime

        config_path = self._config_path
        example_path = os.path.join(os.path.dirname(config_path), "config.json.example")

        # 确认操作
        reply = QMessageBox.question(
            self, self.tr("新建配置"),
            self.tr("将备份当前配置文件并创建空白配置。\n"
            "当前配置会保存为 config.json.bak.{时间戳}\n\n"
            "确定继续?"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # 备份现有配置
        if os.path.exists(config_path):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{config_path}.bak.{timestamp}"
            try:
                shutil.copy2(config_path, backup_path)
            except Exception as e:
                QMessageBox.warning(self, self.tr("备份失败"), self.tr("无法备份配置文件: {0}").format(e))
                return

        # 从模板创建空白配置
        if os.path.exists(example_path):
            try:
                shutil.copy2(example_path, config_path)
            except Exception as e:
                QMessageBox.warning(self, self.tr("创建失败"), self.tr("无法创建空白配置: {0}").format(e))
                return
        else:
            # 模板不存在时创建最小配置
            from ..utils.config_io import save_config
            minimal = {
                "novel_config": {
                    "title": "", "type": "", "theme": "", "style": "",
                    "target_chapters": 10, "chapter_length": 2500,
                    "writing_guide": {}
                },
                "generation_config": {
                    "max_retries": 3, "retry_delay": 30,
                    "outline_batch_max_retries": 3, "outline_batch_retry_delay": 5,
                    "model_selection": {
                        "outline": {"provider": "openai", "model_type": "outline"},
                        "content": {"provider": "openai", "model_type": "content"}
                    },
                    "validation": {"check_logic": True, "check_consistency": True, "check_duplicates": True},
                    "humanization": {
                        "temperature": 0.8,
                        "top_p": 0.9,
                        "dialogue_ratio": 0.4,
                        "description_simplification": True,
                        "emotion_enhancement": True,
                        "enable_humanizer_zh": True
                    }
                },
                "knowledge_base_config": {"reference_files": [], "chunk_size": 1200, "chunk_overlap": 300, "cache_dir": "data/cache"},
                "output_config": {"format": "txt", "encoding": "utf-8", "output_dir": "data/output"}
            }
            save_config(config_path, minimal)

        # 重新加载界面
        self._load_from_file()
        QMessageBox.information(self, self.tr("新建完成"), self.tr("已备份旧配置并创建空白配置,请填写新的小说参数。"))

    # ======================================================================
    # 路径切换 + 重新加载
    # ======================================================================
    def set_config_path(self, path: str):
        self._config_path = path

    def reload(self):
        self._load_from_file()

    def shutdown_workers(self, wait_ms: int = 5000):
        """停止并等待写作指南 worker 结束（主窗口关闭时调用）"""
        w = self._guide_worker
        if w is None:
            return
        try:
            # WritingGuideWorker 本身没有 stop()，尝试通用方式让 QThread 退出
            stop_fn = getattr(w, "stop", None)
            if callable(stop_fn):
                stop_fn()
            w.requestInterruption()
            if w.isRunning():
                w.quit()
                w.wait(wait_ms)
        except RuntimeError:
            # QThread 已被销毁
            pass
        self._guide_worker = None

    # ======================================================================
    # 加载配置
    # ======================================================================
    def _load_from_file(self, silent: bool = False):
        """从 config.json 读取并填充所有字段"""
        if not os.path.exists(self._config_path):
            if not silent:
                QMessageBox.warning(self, self.tr("文件不存在"),
                                    self.tr("配置文件不存在:\n{0}\n\n请通过菜单「文件 → 打开配置文件」选择正确路径,\n或点击「新建配置」创建。").format(self._config_path))
            return
        cfg = load_config(self._config_path)
        nc = cfg.get("novel_config", {})
        gc = cfg.get("generation_config", {})
        kb = cfg.get("knowledge_base_config", {})
        oc = cfg.get("output_config", {})
        ic = cfg.get("imitation_config", {})
        wg = nc.get("writing_guide", {})

        # --- 基本信息 ---
        self._le_title.setText(str(nc.get("title", "")))
        self._le_type.setText(str(nc.get("type", "")))
        self._le_theme.setText(str(nc.get("theme", "")))
        self._le_style.setText(str(nc.get("style", "")))
        self._sp_chapters.setValue(int(nc.get("target_chapters", 100)))
        self._sp_chapter_len.setValue(int(nc.get("chapter_length", 2500)))

        # --- 写作指南：世界观 ---
        wb = wg.get("world_building", {})
        self._te_magic.setPlainText(str(wb.get("magic_system", "")))
        self._te_social.setPlainText(str(wb.get("social_system", "")))
        self._te_bg.setPlainText(str(wb.get("background", "")))

        # --- 写作指南：主角 ---
        prot = _g(wg, "character_guide", "protagonist", default={})
        if isinstance(prot, dict):
            self._te_prot_bg.setPlainText(str(prot.get("background", "")))
            self._te_prot_personality.setPlainText(str(prot.get("initial_personality", "")))
            self._te_prot_growth.setPlainText(str(prot.get("growth_path", "")))

        # --- 写作指南：配角 & 反派（结构化）---
        sr = _g(wg, "character_guide", "supporting_roles", default=[])
        ant = _g(wg, "character_guide", "antagonists", default=[])
        self._load_roles("_sup_data", sr)
        self._load_roles("_ant_data", ant)
        # 角色生成参数：优先从 generation_config.character_generation 读取，
        # 缺失时回退到按现有角色列表长度推断（向后兼容旧配置）
        char_gen = gc.get("character_generation") if isinstance(gc, dict) else None
        if isinstance(char_gen, dict):
            sup_cnt = char_gen.get("supporting_count")
            if isinstance(sup_cnt, (int, float)):
                self._sp_gen_supporting.setValue(int(sup_cnt))
            elif isinstance(sr, list) and sr:
                self._sp_gen_supporting.setValue(len(sr))
            ant_cnt = char_gen.get("antagonist_count")
            if isinstance(ant_cnt, (int, float)):
                self._sp_gen_antagonists.setValue(int(ant_cnt))
            elif isinstance(ant, list) and ant:
                self._sp_gen_antagonists.setValue(len(ant))
            fr = char_gen.get("female_ratio")
            if isinstance(fr, (int, float)):
                self._dsb_gen_female_ratio.setValue(float(fr))
        else:
            if isinstance(sr, list) and sr:
                self._sp_gen_supporting.setValue(len(sr))
            if isinstance(ant, list) and ant:
                self._sp_gen_antagonists.setValue(len(ant))

        # --- 写作指南：剧情结构 ---
        a1 = _g(wg, "plot_structure", "act_one", default={})
        if isinstance(a1, dict):
            self._te_setup.setPlainText(str(a1.get("setup", "")))
            self._te_inciting.setPlainText(str(a1.get("inciting_incident", "")))
            self._te_fp1.setPlainText(str(a1.get("first_plot_point", "")))

        a2 = _g(wg, "plot_structure", "act_two", default={})
        if isinstance(a2, dict):
            self._te_rising.setPlainText(str(a2.get("rising_action", "")))
            self._te_midpoint.setPlainText(str(a2.get("midpoint", "")))
            self._te_complications.setPlainText(str(a2.get("complications", "")))
            self._te_darkest.setPlainText(str(a2.get("darkest_moment", "")))
            self._te_sp2.setPlainText(str(a2.get("second_plot_point", "")))

        a3 = _g(wg, "plot_structure", "act_three", default={})
        if isinstance(a3, dict):
            self._te_climax.setPlainText(str(a3.get("climax", "")))
            self._te_resolution.setPlainText(str(a3.get("resolution", "")))
            self._te_denouement.setPlainText(str(a3.get("denouement", "")))

        # 节奏锚点（disasters）
        disasters = _g(wg, "plot_structure", "disasters", default={})
        if isinstance(disasters, dict):
            self._te_disaster_1.setPlainText(str(disasters.get("first_disaster", "")))
            self._te_disaster_2.setPlainText(str(disasters.get("second_disaster", "")))
            self._te_disaster_3.setPlainText(str(disasters.get("third_disaster", "")))

        # --- 写作指南：风格 ---
        sg = wg.get("style_guide", {})
        self._te_tone.setPlainText(str(sg.get("tone", "")))
        self._te_pacing.setPlainText(str(sg.get("pacing", "")))
        # description_focus 列表
        df = sg.get("description_focus", [])
        if isinstance(df, list):
            self._desc_focus_data = [str(x) for x in df]
        elif isinstance(df, str) and df:
            self._desc_focus_data = [df]
        else:
            self._desc_focus_data = []
        self._refresh_desc_focus_list()
        if self._desc_focus_data:
            self._lw_desc_focus.setCurrentRow(0)
        else:
            self._focus_updating = True
            self._te_desc_focus_detail.clear()
            self._focus_updating = False

        # --- 生成配置：大纲参数 ---
        self._sp_batch_size.setValue(int(gc.get("batch_size", 10)))
        self._sp_outline_batch.setValue(int(gc.get("outline_batch_size", 100)))
        self._sp_context_chapters.setValue(int(gc.get("outline_context_chapters", 10)))
        self._sp_detail_chapters.setValue(int(gc.get("outline_detail_chapters", 5)))

        # --- 生成配置：卷结构 ---
        arc_cfg = nc.get("arc_config", {})
        self._sp_chapters_per_arc.setValue(int(arc_cfg.get("chapters_per_arc", 0)))

        # --- 生成配置：验证 ---
        val = gc.get("validation", {})
        self._cb_logic.setChecked(bool(val.get("check_logic", True)))
        self._cb_consistency.setChecked(bool(val.get("check_consistency", True)))
        self._cb_duplicates.setChecked(bool(val.get("check_duplicates", True)))

        # --- 生成配置：人性化 ---
        hum = gc.get("humanization", {})
        self._dsb_temp.setValue(float(hum.get("temperature", 0.8)))
        self._dsb_top_p.setValue(float(hum.get("top_p", 0.9)))
        self._dsb_dialogue.setValue(float(hum.get("dialogue_ratio", 0.4)))
        self._cb_desc_simp.setChecked(bool(hum.get("description_simplification", True)))
        self._cb_emotion.setChecked(bool(hum.get("emotion_enhancement", True)))
        self._cb_humanizer_zh.setChecked(bool(hum.get("enable_humanizer_zh", True)))

        # --- 知识库 ---
        self._lw_refs.clear()
        for f in kb.get("reference_files", []):
            self._lw_refs.addItem(str(f))
        self._sp_chunk.setValue(int(kb.get("chunk_size", 1200)))
        self._sp_overlap.setValue(int(kb.get("chunk_overlap", 300)))

        # --- 仿写配置 ---
        self._cb_imit_enabled.setChecked(bool(ic.get("enabled", False)))
        auto = ic.get("auto_imitation", {})
        self._cb_auto_imit.setChecked(bool(auto.get("enabled", False)))
        self._cb_trigger_all.setChecked(bool(auto.get("trigger_all_chapters", False)))
        self._le_output_suffix.setText(str(auto.get("output_suffix", "_imitated")))
        self._cb_backup_original.setChecked(bool(auto.get("backup_original", False)))
        # 风格源列表
        ss = auto.get("style_sources", [])
        self._style_sources_data = ss if isinstance(ss, list) else []
        self._refresh_style_list()
        if self._style_sources_data:
            self._lw_styles.setCurrentRow(0)
        # 默认风格下拉框
        default_style = str(auto.get("default_style", "古风雅致"))
        idx = self._le_default_style.findText(default_style)
        if idx >= 0:
            self._le_default_style.setCurrentIndex(idx)
        manual = ic.get("manual_imitation", {})
        self._cb_manual_imit.setChecked(bool(manual.get("enabled", True)))
        self._le_imit_output_dir.setText(str(manual.get("default_output_dir", "data/imitation_output")))
        qc = ic.get("quality_control", {})
        self._dsb_min_similarity.setValue(float(qc.get("min_style_similarity", 0.7)))
        self._sp_imit_retries.setValue(int(qc.get("max_retries", 3)))
        self._cb_content_check.setChecked(bool(qc.get("content_preservation_check", True)))
        self._cb_style_check.setChecked(bool(qc.get("style_consistency_check", True)))

        # --- 输出 ---
        self._le_output_dir.setText(str(oc.get("output_dir", "data/output")))

        # --- 故事创意：从 output_dir/core_seed.txt 同步 ---
        # 切换配置文件时,输入框应反映新配置目录下的种子文件内容,
        # 而不是停留在上一次加载的旧种子。
        self._autofill_story_idea_from_core_seed(str(oc.get("output_dir", "data/output")))

    # ------------------------------------------------------------------
    # 故事创意自动填充
    # ------------------------------------------------------------------
    def _autofill_story_idea_from_core_seed(self, output_dir: str) -> None:
        """从 output_dir/core_seed.txt 同步故事创意输入框

        策略:
        - 若 core_seed.txt 存在且非空 → **覆盖**当前输入框(无论是否已有内容)
          这样每次加载/切换配置时,输入框总是反映该配置目录下的真实种子;
          手动输入未持久化为种子文件的创意会被磁盘种子覆盖(视为预期)。
        - 若 core_seed.txt 不存在或为空 → 不动当前输入框
          (避免误清空用户尚未生成种子的手动输入)。
        - 若新内容与当前内容相同 → 跳过 setText 以避免不必要的信号触发。

        路径解析:
        1. 绝对路径直接用;
        2. 相对路径相对当前 cwd;
        3. 仍不存在时再相对 config.json 所在目录解析。
        """
        try:
            output_dir = (output_dir or "").strip()
            if not output_dir:
                return

            candidates: list[str] = []
            if os.path.isabs(output_dir):
                candidates.append(os.path.join(output_dir, "core_seed.txt"))
            else:
                candidates.append(os.path.join(output_dir, "core_seed.txt"))
                if getattr(self, "_config_path", ""):
                    cfg_dir = os.path.dirname(os.path.abspath(self._config_path))
                    candidates.append(os.path.join(cfg_dir, output_dir, "core_seed.txt"))

            for path in candidates:
                if not os.path.isfile(path):
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    seed = f.read().strip()
                if not seed:
                    _logger.info(f"core_seed.txt 内容为空，未更新故事创意: {path}")
                    return
                current = self._le_story_idea.text().strip()
                if current == seed:
                    return  # 已一致,无需重置
                self._le_story_idea.setText(seed)
                _logger.info(f"已加载故事核心种子作为故事创意: {path}")
                return
        except Exception as e:
            _logger.warning(f"自动加载 core_seed.txt 失败: {e}", exc_info=True)

    # ======================================================================
    # 保存配置
    # ======================================================================
    def _save_to_file(self):
        """收集所有字段值,合并回 config.json 并写入"""
        # 先加载原始配置,保留本 Tab 不管理的字段
        cfg = load_config(self._config_path)

        # --- 收集配角/反派（结构化列表，过滤完全空白项）---
        def _clean_roles(data: list[dict]) -> list[dict]:
            cleaned = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                # 至少一个非空字段才保留
                if any(str(v).strip() for v in item.values()):
                    cleaned.append({k: (v if v is not None else "") for k, v in item.items()})
            return cleaned

        supporting = _clean_roles(self._sup_data)
        antagonists = _clean_roles(self._ant_data)

        # --- 组装 novel_config ---
        nc = cfg.setdefault("novel_config", {})
        nc["title"] = self._le_title.text()
        nc["type"] = self._le_type.text()
        nc["theme"] = self._le_theme.text()
        nc["style"] = self._le_style.text()
        nc["target_chapters"] = self._sp_chapters.value()
        nc["chapter_length"] = self._sp_chapter_len.value()
        nc["arc_config"] = {
            "chapters_per_arc": self._sp_chapters_per_arc.value(),
        }

        wg = nc.setdefault("writing_guide", {})
        wg["world_building"] = {
            "magic_system": self._te_magic.toPlainText(),
            "social_system": self._te_social.toPlainText(),
            "background": self._te_bg.toPlainText(),
        }
        wg["character_guide"] = {
            "protagonist": {
                "background": self._te_prot_bg.toPlainText(),
                "initial_personality": self._te_prot_personality.toPlainText(),
                "growth_path": self._te_prot_growth.toPlainText(),
            },
            "supporting_roles": supporting,
            "antagonists": antagonists,
        }
        wg["plot_structure"] = {
            "act_one": {
                "setup": self._te_setup.toPlainText(),
                "inciting_incident": self._te_inciting.toPlainText(),
                "first_plot_point": self._te_fp1.toPlainText(),
            },
            "act_two": {
                "rising_action": self._te_rising.toPlainText(),
                "midpoint": self._te_midpoint.toPlainText(),
                "complications": self._te_complications.toPlainText(),
                "darkest_moment": self._te_darkest.toPlainText(),
                "second_plot_point": self._te_sp2.toPlainText(),
            },
            "act_three": {
                "climax": self._te_climax.toPlainText(),
                "resolution": self._te_resolution.toPlainText(),
                "denouement": self._te_denouement.toPlainText(),
            },
            "disasters": {
                "first_disaster": self._te_disaster_1.toPlainText(),
                "second_disaster": self._te_disaster_2.toPlainText(),
                "third_disaster": self._te_disaster_3.toPlainText(),
            },
        }
        sg = wg.setdefault("style_guide", {})
        sg["tone"] = self._te_tone.toPlainText()
        sg["pacing"] = self._te_pacing.toPlainText()
        # description_focus: 过滤空项，保留非空字符串列表
        sg["description_focus"] = [s.strip() for s in self._desc_focus_data if s and s.strip()]

        # --- 组装 generation_config ---
        gc = cfg.setdefault("generation_config", {})
        gc["batch_size"] = self._sp_batch_size.value()
        gc["outline_batch_size"] = self._sp_outline_batch.value()
        gc["outline_context_chapters"] = self._sp_context_chapters.value()
        gc["outline_detail_chapters"] = self._sp_detail_chapters.value()
        gc.setdefault("validation", {}).update({
            "check_logic": self._cb_logic.isChecked(),
            "check_consistency": self._cb_consistency.isChecked(),
            "check_duplicates": self._cb_duplicates.isChecked(),
        })
        gc.setdefault("humanization", {}).update({
            "temperature": self._dsb_temp.value(),
            "top_p": self._dsb_top_p.value(),
            "dialogue_ratio": self._dsb_dialogue.value(),
            "description_simplification": self._cb_desc_simp.isChecked(),
            "emotion_enhancement": self._cb_emotion.isChecked(),
            "enable_humanizer_zh": self._cb_humanizer_zh.isChecked(),
        })
        # 持久化角色生成参数（配角数 / 反派数 / 女性比例），否则重开界面会回退
        gc["character_generation"] = {
            "supporting_count": self._sp_gen_supporting.value(),
            "antagonist_count": self._sp_gen_antagonists.value(),
            "female_ratio": self._dsb_gen_female_ratio.value(),
        }

        # --- 组装 knowledge_base_config ---
        kb = cfg.setdefault("knowledge_base_config", {})
        kb["reference_files"] = [
            self._lw_refs.item(i).text() for i in range(self._lw_refs.count())
        ]
        kb["chunk_size"] = self._sp_chunk.value()
        kb["chunk_overlap"] = self._sp_overlap.value()

        # --- 组装 imitation_config ---
        ic = cfg.setdefault("imitation_config", {})
        ic["enabled"] = self._cb_imit_enabled.isChecked()
        auto = ic.setdefault("auto_imitation", {})
        auto["enabled"] = self._cb_auto_imit.isChecked()
        auto["trigger_all_chapters"] = self._cb_trigger_all.isChecked()
        auto["default_style"] = self._le_default_style.currentText()
        auto["output_suffix"] = self._le_output_suffix.text()
        auto["backup_original"] = self._cb_backup_original.isChecked()
        auto["style_sources"] = self._style_sources_data
        manual = ic.setdefault("manual_imitation", {})
        manual["enabled"] = self._cb_manual_imit.isChecked()
        manual["default_output_dir"] = self._le_imit_output_dir.text()
        qc = ic.setdefault("quality_control", {})
        qc["min_style_similarity"] = self._dsb_min_similarity.value()
        qc["max_retries"] = self._sp_imit_retries.value()
        qc["content_preservation_check"] = self._cb_content_check.isChecked()
        qc["style_consistency_check"] = self._cb_style_check.isChecked()

        # --- 组装 output_config ---
        oc = cfg.setdefault("output_config", {})
        oc["output_dir"] = self._le_output_dir.text()

        # 写入文件
        save_config(self._config_path, cfg)
        QMessageBox.information(self, self.tr("保存成功"), self.tr("配置已保存到 config.json"))

    # ======================================================================
    # 目标章节数变化 → 自适应角色数量建议
    # ======================================================================
    def _on_chapters_changed(self, chapters: int):
        """根据目标章节数自动调整配角/反派数量的建议默认值"""
        if chapters <= 30:
            sup, ant = 3, 2
        elif chapters <= 100:
            sup, ant = 6, 4
        elif chapters <= 300:
            sup, ant = 10, 6
        else:
            sup, ant = 15, 8
        # 仅当用户未手动修改过时才自动更新（tooltip 同时说明语义）
        self._sp_gen_supporting.setToolTip(
            self.tr("配角的目标总数；本次实际新增 = 目标 - 已有数量(下限 0)。当前篇幅 {0} 章，建议 {1} 个").format(chapters, sup))
        self._sp_gen_antagonists.setToolTip(
            self.tr("反派的目标总数；本次实际新增 = 目标 - 已有数量(下限 0)。当前篇幅 {0} 章，建议 {1} 个").format(chapters, ant))

    # ======================================================================
    # 自动生成写作指南
    # ======================================================================
    def _on_generate_guide(self):
        """启动后台线程生成写作指南

        增补模式语义:
        - 配角/反派的 spinbox 表示"目标总数",而非"本次新增数量";
        - 真正传给 worker 的 n_supporting/n_antagonists 是
            max(0, 目标总数 - 已有数量);
        - 这样用户在已有 4 个配角时填 6,只会让模型新增 2 个,
            而不是新增 6 个再去重(避免溢出)。
        - 若 diff <= 0,worker 仍被启动以更新世界观/主角/剧情等其他字段,
            但角色列表传 0 表示不再生成新角色。
        """
        story_idea = self._le_story_idea.text().strip()
        title = self._le_title.text().strip()
        novel_type = self._le_type.text().strip()
        theme = self._le_theme.text().strip()
        style = self._le_style.text().strip()

        if not story_idea:
            QMessageBox.warning(self, self.tr("缺少信息"), self.tr("请先输入简短的故事创意。"))
            self._le_story_idea.setFocus()
            return

        # 计算"实际需要新增的角色数" = 目标总数 - 已有数量(下限 0)
        target_sup = self._sp_gen_supporting.value()
        target_ant = self._sp_gen_antagonists.value()
        existing_sup = len(getattr(self, "_sup_data", []) or [])
        existing_ant = len(getattr(self, "_ant_data", []) or [])
        n_sup_to_gen = max(0, target_sup - existing_sup)
        n_ant_to_gen = max(0, target_ant - existing_ant)
        # 缓存供 _on_guide_result 在弹框中说明
        self._guide_target_sup = target_sup
        self._guide_target_ant = target_ant
        self._guide_existing_sup = existing_sup
        self._guide_existing_ant = existing_ant
        self._guide_request_sup = n_sup_to_gen
        self._guide_request_ant = n_ant_to_gen

        _logger.info(
            f"自动生成写作指南: 配角 目标 {target_sup} / 已有 {existing_sup} / 新增请求 {n_sup_to_gen}; "
            f"反派 目标 {target_ant} / 已有 {existing_ant} / 新增请求 {n_ant_to_gen}"
        )

        self._btn_gen_guide.setEnabled(False)
        self._btn_gen_guide.setText(self.tr("正在生成…"))

        self._guide_worker = WritingGuideWorker(
            env_path=self._env_path,
            story_idea=story_idea,
            title=title or self.tr("未命名"),
            novel_type=novel_type or self.tr("通用"),
            theme=theme or self.tr("通用"),
            style=style or self.tr("通用"),
            n_supporting=n_sup_to_gen,
            n_antagonists=n_ant_to_gen,
            female_ratio=self._dsb_gen_female_ratio.value(),
            target_chapters=self._sp_chapters.value(),
            chapter_length=self._sp_chapter_len.value(),
            parent=self,
        )
        self._guide_worker.finished_result.connect(self._on_guide_result)
        self._guide_worker.start()

    def _on_guide_result(self, success: bool, result):
        """处理写作指南生成结果（增补模式：仅填空字段，列表追加唯一项）"""
        self._btn_gen_guide.setEnabled(True)
        self._btn_gen_guide.setText(self.tr("自动生成写作指南"))

        if not success:
            QMessageBox.warning(self, self.tr("生成失败"), str(result))
            return

        # 统计增补 / 跳过 数量，便于在结束提示中告知用户
        filled = 0
        skipped = 0

        def _try_fill(widget, value) -> None:
            nonlocal filled, skipped
            if self._set_text_if_empty(widget, value):
                filled += 1
            else:
                if str(value or "").strip():
                    skipped += 1

        # 写作指南：世界观
        wg = result
        wb = wg.get("world_building", {})
        _try_fill(self._te_magic, wb.get("magic_system", ""))
        _try_fill(self._te_social, wb.get("social_system", ""))
        _try_fill(self._te_bg, wb.get("background", ""))

        # 写作指南：主角
        prot = _g(wg, "character_guide", "protagonist", default={})
        if isinstance(prot, dict):
            _try_fill(self._te_prot_bg, prot.get("background", ""))
            _try_fill(self._te_prot_personality, prot.get("initial_personality", ""))
            _try_fill(self._te_prot_growth, prot.get("growth_path", ""))

        # 写作指南：配角 & 反派（按 name 去重追加）
        sr = _g(wg, "character_guide", "supporting_roles", default=[])
        ant = _g(wg, "character_guide", "antagonists", default=[])
        sup_before = len(self._sup_data)
        ant_before = len(self._ant_data)
        self._merge_roles("_sup_data", sr)
        self._merge_roles("_ant_data", ant)
        sup_added = len(self._sup_data) - sup_before
        ant_added = len(self._ant_data) - ant_before

        # 剧情结构
        a1 = _g(wg, "plot_structure", "act_one", default={})
        if isinstance(a1, dict):
            _try_fill(self._te_setup, a1.get("setup", ""))
            _try_fill(self._te_inciting, a1.get("inciting_incident", ""))
            _try_fill(self._te_fp1, a1.get("first_plot_point", ""))

        a2 = _g(wg, "plot_structure", "act_two", default={})
        if isinstance(a2, dict):
            _try_fill(self._te_rising, a2.get("rising_action", ""))
            _try_fill(self._te_midpoint, a2.get("midpoint", ""))
            _try_fill(self._te_complications, a2.get("complications", ""))
            _try_fill(self._te_darkest, a2.get("darkest_moment", ""))
            _try_fill(self._te_sp2, a2.get("second_plot_point", ""))

        a3 = _g(wg, "plot_structure", "act_three", default={})
        if isinstance(a3, dict):
            _try_fill(self._te_climax, a3.get("climax", ""))
            _try_fill(self._te_resolution, a3.get("resolution", ""))
            _try_fill(self._te_denouement, a3.get("denouement", ""))

        disasters = _g(wg, "plot_structure", "disasters", default={})
        if isinstance(disasters, dict):
            _try_fill(self._te_disaster_1, disasters.get("first_disaster", ""))
            _try_fill(self._te_disaster_2, disasters.get("second_disaster", ""))
            _try_fill(self._te_disaster_3, disasters.get("third_disaster", ""))

        # 风格指南
        sg = wg.get("style_guide", {})
        _try_fill(self._te_tone, sg.get("tone", ""))
        _try_fill(self._te_pacing, sg.get("pacing", ""))

        # description_focus 列表：追加唯一项（按内容去重）
        df = sg.get("description_focus", [])
        new_focus_items: list[str] = []
        if isinstance(df, list):
            new_focus_items = [str(x) for x in df if str(x).strip()]
        elif isinstance(df, str) and df.strip():
            new_focus_items = [df]

        existing_focus = {str(x).strip() for x in self._desc_focus_data if str(x).strip()}
        focus_before = len(self._desc_focus_data)
        for item in new_focus_items:
            key = item.strip()
            if key and key not in existing_focus:
                self._desc_focus_data.append(item)
                existing_focus.add(key)
        focus_added = len(self._desc_focus_data) - focus_before
        self._refresh_desc_focus_list()
        if self._desc_focus_data and self._lw_desc_focus.currentRow() < 0:
            self._lw_desc_focus.setCurrentRow(0)

        # 用户提示：明确"增补"语义，避免以为没生效
        msg_lines = [self.tr("写作指南已按增补模式更新（仅填空、列表追加）。")]
        msg_lines.append(self.tr("文本字段：填入 {0} 项，跳过 {1} 项已有内容。").format(filled, skipped))
        msg_lines.append(self.tr("描写侧重追加 {0} 条。").format(focus_added))
        # 配角/反派的总数变化（spinbox 表示目标总数）
        target_sup = getattr(self, "_guide_target_sup", None)
        target_ant = getattr(self, "_guide_target_ant", None)
        if target_sup is not None and target_ant is not None:
            sup_total = len(self._sup_data)
            ant_total = len(self._ant_data)
            sup_existed = getattr(self, "_guide_existing_sup", sup_total - sup_added)
            ant_existed = getattr(self, "_guide_existing_ant", ant_total - ant_added)
            msg_lines.append(self.tr(
                "配角：目标总数 {0}，已有 {1} → 现 {2}（新增 {3}）；"
                "反派：目标总数 {4}，已有 {5} → 现 {6}（新增 {7}）。"
            ).format(target_sup, sup_existed, sup_total, sup_added,
                     target_ant, ant_existed, ant_total, ant_added))
        else:
            msg_lines.append(self.tr("配角追加 {0} 个，反派追加 {1} 个。").format(sup_added, ant_added))
        msg_lines.append(self.tr("如需完全重写，请先清空对应字段后再点击「自动生成写作指南」。"))
        QMessageBox.information(self, self.tr("生成完成"), "\n".join(msg_lines))

    # ======================================================================
    # 编辑锁定（保留滚动）
    # ======================================================================
    def set_editing_enabled(self, enabled: bool):
        """启用/禁用所有输入控件，但不影响滚动"""
        for child in self.findChildren(QLineEdit):
            child.setEnabled(enabled)
        for child in self.findChildren(QTextEdit):
            child.setEnabled(enabled)
        for child in self.findChildren(QSpinBox):
            child.setEnabled(enabled)
        for child in self.findChildren(QDoubleSpinBox):
            child.setEnabled(enabled)
        for child in self.findChildren(QCheckBox):
            child.setEnabled(enabled)
        for child in self.findChildren(QComboBox):
            child.setEnabled(enabled)
        for child in self.findChildren(QPushButton):
            child.setEnabled(enabled)

    def changeEvent(self, event):
        """语言切换时传播事件到子组件"""
        if event.type() == QEvent.Type.LanguageChange:
            pass  # 子组件通过 findChildren 自动接收事件
        super().changeEvent(event)
