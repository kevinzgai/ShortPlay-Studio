"""跨模块共享的常量：提示词模板、风格锚点、镜头字段白名单。

集中放置的原因：assets / render / 出图链路都要用 STYLE_ANCHOR_* 与 NEGATIVE_DEFAULT，
各模块各复制一份迟早会漂。这里只放**常量**，不放任何逻辑。
"""

import re


SIZE_SET = {"远景", "全景", "中景", "近景", "特写"}


KIND_SET = {"establishing", "action", "dialogue", "closing"}


DETAIL_FIELDS = ("subject", "action", "composition", "sizeReason", "camera",
                 "light", "mood", "sound", "transition")


GENERIC_RE = re.compile(
    r"画面(?:缓缓|慢慢)(?:地)?展开|镜头(?:缓缓|慢慢)(?:地)?拉远|氛围收进画面|"
    r"留出转场余韵|安静地停留片刻|交代空间关系|镜头缓缓展开"
)


STYLE_ANCHOR_DEFAULT = "写实电影质感 · 35mm 胶片颗粒 · 冷调 · 无滤镜磨皮"


STYLE_ANCHOR_EN_DEFAULT = ("photorealistic cinematic film still, 35mm film grain, "
                           "cool desaturated color grade, natural skin texture, "
                           "no beautification filter")


NEGATIVE_DEFAULT = ("模糊，低清晰度，多余的手指，畸形的四肢，现代感强的插画风，3D渲染，"
                    "动漫感，塑料皮肤，过度磨皮，脸部对称过度，英文字幕，水印，logo，鲜艳高饱和，暖色调")


SIZE_EN = {"远景": "extreme wide shot", "全景": "wide shot", "中景": "medium shot",
           "近景": "medium close-up", "特写": "close-up"}


TURNAROUND_TMPL = (
    "角色设定表，三视图并排（最左为正面全身，中间为侧面全身，最右为背面全身，"
    "三者等比例、足底对齐、同一人），全身远景，纯白色无缝背景，无阴影投射，画面里没有道具和场景。\n"
    "三个视图必须是同一个人：脸型、发型、服装完全一致，不要出现第二张脸。\n"
    "{keyword}\n"
    "面部特征：{face}；可辨识瑕疵：{flaw}。\n"
    "服装：{wardrobe}。配饰与记忆点：{wardrobeHook}。\n"
    "{style}。上面的风格只作用于色调与质感，不要把霓虹、雨夜之类的场景元素画进背景。"
    "写实电影质感，均匀柔光，正面与侧面两张的脸要清晰可辨（眼睛、鼻子、唇形看得清）；"
    "布料纤维与磨损痕迹清晰可见。表情：中性。\n"
    "比例 1:1 方形。\n"
    "负面词（仅豆包 / 即梦等支持负面提示词的引擎有效；Flux 没有负面通道，"
    "要把这些改写成正面描述）：{negative}"
)


FACE_SHEET_TMPL = (
    "角色面部四视图，横向并排四张头部特写：正面、四分之三侧、正侧、微仰角。"
    "只画头部与肩部（胸像构图），不画全身；四张是同一个人，脸型与发型完全一致，纯白色背景。\n"
    "{keyword}\n面部特征：{face}；瑕疵：{flaw}；配饰：{wardrobeHook}。\n"
    "{style}。写实电影质感，柔和均匀光，眼睛与嘴唇清晰，皮肤有真实毛孔与肤色过渡。"
    "比例 3:2 横版。\n"
    "这张图只负责把脸定准；体型与服装看三视图。"
)


CONCEPT_TMPL = (
    "场景概念图，{name}{tags}。\n"
    "陈设与细节：{props}。\n"
    "物理光影：{light}。\n"
    "材质细节：真实材质与岁月痕迹，无塑料感，无过度磨皮。\n"
    "镜头：{lens}，纵深构图。{style}。写实电影质感，35mm 胶片，浓郁颗粒，"
    "高动态范围，深邃阴影，8k超高清。\n"
    "比例 16:9 横版；核心场景另出 2.35:1 宽银幕版。负面词：{negative}"
)


FRAME_TMPL = (
    "{style}。单帧电影剧照，{aspect}，本镜第 0 帧（起始帧）："
    "不要三视图、不要设定表、不要拼贴图、不要画面文字。\n"
    "出场角色（固定特征原样保持，不得重写）：{keywords}\n"
    "场景：{scene}；{scene_props}；{scene_light}。\n"
    "画面主体：{subject}。动作起点：{action}。\n"
    "构图与机位：{composition}；景别：{size}；运镜：{camera}。\n"
    "光线：{light}。情绪：{mood}。\n"
    "{lens}。写实电影质感，35mm 胶片颗粒，高动态范围，深邃阴影，8k超高清。\n"
    "负面词：{negative}"
)


ASSET_KIND_CN = {"character": "角色", "scene": "场景", "prop": "道具"}


SOURCE_CN = {"script": "剧本原文", "inferred": "AI 推断", "manual": "手工新增", "user": "手工修改"}


SYSTEM_ASSET_FILL = """你是短剧美术设定总监。只输出严格 JSON，不要解释文字，不要 Markdown 代码块。

你会拿到一个资产（角色、场景或道具）的名字、剧本中与它相关的原文片段、以及界面上已经填好的字段。
请补全这个资产的视觉设定，让用户可以直接拿去出图。

角色输出：
{"age":"18岁","role":"主角","face":"脸型与五官，15字内","flaw":"一处可辨识瑕疵，12字内",
 "wardrobeHook":"服装或配饰记忆点，12字内","wardrobe":"服装一句话，20字内",
 "keyword":"把 age、face、flaw、wardrobeHook、wardrobe 用中文逗号连成一句，40字内",
 "keywordEn":"同一串的英文版，给本地 Flux 用，一句，40词内"}

场景输出：
{"appearance":"环境一句话，30字内","light":"主光与色温，20字内","lens":"镜头焦段，如 24mm广角",
 "props":["陈设A","陈设B"],"sceneEn":"一句英文场景描述，给本地 Flux 用，30词内"}

道具输出：
{"appearance":"材质、颜色、尺寸、年代感或磨损，25字内（只写物体本身，不写属于谁）",
 "propEn":"一句英文静物描述，给本地 Flux 用，含材质与颜色，20词内"}

硬性规则：
- 剧本原文里写明的细节必须原样保留，不许改写；推断出的细节不要写成确定事实。
- 已经填好的非空字段，除非明显与剧本冲突，否则保持不变。
- 严禁新增剧本里没有的情节、身世、结局；严禁输出长段描述文字。
- 三个一致性锚点（face / flaw / wardrobeHook）必须给，且要具体到能画出区别。
- keyword 各段必须用中文逗号「，」分隔。keywordEn / sceneEn / propEn 必须是英文。
- 道具只描述物体本身：appearance 不写持有者、不写人物；propEn 必须是英文静物短语，
  不许出现 a man / woman / someone holding / hand / person 一类词。
- 只输出一个 JSON 对象。"""
