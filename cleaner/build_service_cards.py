from __future__ import annotations

from pathlib import PurePosixPath
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
CARD_DIR = ROOT / "data" / "cleaned" / "service_cards"
DOWNLOAD_SUFFIXES = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar"}
REQUEST_HEADERS = {"User-Agent": "JNU-Student-Assistant/0.4 (+public educational project)"}


CARDS = [
    {
        "filename": "本科生请假申请表.md",
        "title": "本科生请假申请表",
        "category": "请假",
        "department": "本科生院",
        "answer": "本科生请假申请表在暨南大学本科生院“下载服务 - 学籍相关文件”栏目中，材料名称为“本科学生请假申请表202504”，发布时间为 2025-04-16，可直接打开具体事项页面下载。",
        "source": "https://jwc.jnu.edu.cn/2025/0409/c6757a833626/page.htm",
        "keywords": "请假, 请假申请表, 本科学生请假申请表202504, 学籍相关文件, 本科生院",
    },
    {
        "filename": "转专业申请表.md",
        "title": "转专业申请表",
        "category": "转专业",
        "department": "本科生院",
        "answer": "根据暨南大学本科生院 2025—2026 学年转专业通知，学生须在规定时间登录新综合教务系统填写《转专业申请表》，提交后打印签名；当前申请表由系统生成，不提供独立公开下载文件。",
        "source": "https://jwc.jnu.edu.cn/2026/0424/c6765a854250/page.htm",
        "entrance": "暨南大学新综合教务系统转专业申请入口",
        "materials": "系统生成的转专业申请表、成绩单及通知要求的证明材料",
        "service_type": "在线办理",
        "keywords": "转专业, 转专业申请表, 内招生, 外招生, 新综合教务系统, 转专业通知",
    },
    {
        "filename": "复学休学申请表.md",
        "title": "复学和休学申请表",
        "category": "学籍",
        "department": "本科生院",
        "answer": "复学和休学相关表格在暨南大学本科生院“下载服务 - 学籍相关文件”栏目中，可见“FX1_复学申请表202504”和“XX1_休学申请表202504”，复学申请表可直接打开具体事项页面。",
        "source": "https://jwc.jnu.edu.cn/2021/0313/c6757a600999/page.htm",
        "keywords": "复学, 休学, 复学申请表, 休学申请表, FX1, XX1, 学籍",
    },
    {
        "filename": "成绩单在学证明打印.md",
        "title": "成绩单和在学证明打印",
        "category": "成绩证明",
        "department": "本科生院",
        "answer": "成绩单、在学证明等办理说明在暨南大学本科生院“学生办事指南”栏目中，事项名称为“打印中英文成绩单、证明等”，可直接打开具体事项页面查看。",
        "source": "https://jwc.jnu.edu.cn/2021/0317/c11805a602515/page.htm",
        "keywords": "成绩单, 在学证明, 中英文成绩单, 打印证明, 学生办事指南",
    },
    {
        "filename": "学生证补办.md",
        "title": "学生证遗失补办",
        "category": "学生证",
        "department": "本科生院",
        "answer": "学生证遗失补办说明在暨南大学本科生院“学生办事指南”栏目中，事项名称为“在校全日制本科生遗失学生证补办”，可直接打开具体事项页面查看。",
        "source": "https://jwc.jnu.edu.cn/2019/0418/c11805a310048/page.htm",
        "keywords": "学生证, 学生证补办, 遗失学生证, 全日制本科生, 学生办事指南",
    },
    {
        "filename": "新生保留入学资格申请表.md",
        "title": "新生保留入学资格申请表",
        "category": "新生",
        "department": "招生办公室",
        "answer": "本科新生保留入学资格申请表在暨南大学招生办公室“下载中心”栏目中，材料名称为“暨南大学本科新生保留入学资格申请表”，发布时间为 2022-08-24，可直接打开具体事项页面下载。",
        "source": "https://zsb.jnu.edu.cn/2022/0824/c3464a713673/page.htm",
        "keywords": "新生, 保留入学资格, 本科新生保留入学资格申请表, 招生办公室, 下载中心",
    },
    {
        "filename": "新生放弃入学资格申请表.md",
        "title": "新生放弃入学资格申请表",
        "category": "新生",
        "department": "招生办公室",
        "answer": "本科新生放弃入学资格申请表在暨南大学招生办公室“下载中心”栏目中，材料名称为“暨南大学本科新生放弃入学资格申请表”，发布时间为 2022-08-15，可直接打开具体事项页面下载。",
        "source": "https://zsb.jnu.edu.cn/2022/0815/c3464a712943/page.htm",
        "keywords": "新生, 放弃入学资格, 本科新生放弃入学资格申请表, 招生办公室, 下载中心",
    },
    {
        "filename": "本科学生主动退学申请表.md",
        "title": "本科学生主动退学申请表",
        "category": "学籍",
        "department": "本科生院",
        "answer": "暨南大学本科生院“学籍相关文件”栏目列有“本科学生主动退学申请表”（2025-07-16），但具体文件页面当前需要统一身份认证，未发现可公开直连下载的官方附件；请从学校认证入口办理或向学院教科办索取。",
        "source": "https://jwc.jnu.edu.cn/6747/list.htm",
        "entrance": "暨南大学统一身份认证后的本科生院学籍业务入口",
        "service_type": "认证办理",
        "keywords": "退学, 主动退学, 本科学生主动退学申请表, 学籍相关文件, 本科生院",
    },
    {
        "filename": "学生注销学籍申请表.md",
        "title": "学生注销学籍申请表",
        "category": "学籍",
        "department": "本科生院",
        "answer": "学生注销学籍申请表在暨南大学本科生院“下载服务 - 学籍相关文件”栏目中，材料名称为“学生注销学籍申请表（本科）”，发布时间为 2022-04-26，可直接打开具体事项页面下载。",
        "source": "https://jwc.jnu.edu.cn/2022/0426/c6757a693361/page.htm",
        "keywords": "注销学籍, 学籍注销, 学生注销学籍申请表, 本科, 学籍相关文件",
    },
    {
        "filename": "学士学位证明书申请表.md",
        "title": "学士学位证明书申请表",
        "category": "成绩证明",
        "department": "本科生院",
        "answer": "学士学位证明书申请表在暨南大学本科生院“下载服务 - 学籍相关文件”栏目中，材料名称为“学士学位证明书申请表”，发布时间为 2021-03-13，可直接打开具体事项页面下载。",
        "source": "https://jwc.jnu.edu.cn/2021/0313/c6757a600957/page.htm",
        "keywords": "学士学位证明书, 学位证明, 学位证明书申请表, 学籍相关文件",
    },
    {
        "filename": "学位证书遗失补办.md",
        "title": "学位证书遗失补办",
        "category": "证书补办",
        "department": "本科生院",
        "answer": "全日制本科学生学位证书遗失补办说明在暨南大学本科生院“学生办事指南”栏目中，事项名称为“全日制本科学生学位证书遗失补办”，发布时间为 2021-03-17，可直接打开具体事项页面查看。",
        "source": "https://jwc.jnu.edu.cn/2021/0317/c11805a602511/page.htm",
        "keywords": "学位证书, 学位证遗失, 学位证补办, 全日制本科学生, 学生办事指南",
    },
    {
        "filename": "毕业证书遗失补办.md",
        "title": "毕业证书遗失补办",
        "category": "证书补办",
        "department": "本科生院",
        "answer": "全日制本科学生毕业证书遗失补办说明在暨南大学本科生院“学生办事指南”栏目中，事项名称为“全日制本科学生毕业证书遗失补办”，发布时间为 2021-03-17，可直接打开具体事项页面查看。",
        "source": "https://jwc.jnu.edu.cn/2021/0317/c11805a602509/page.htm",
        "keywords": "毕业证书, 毕业证遗失, 毕业证补办, 全日制本科学生, 学生办事指南",
    },
    {
        "filename": "学生选课流程.md",
        "title": "学生选课流程",
        "category": "考试选课",
        "department": "本科生院",
        "answer": "学生选课流程说明在暨南大学本科生院“学生办事指南”栏目中，事项名称为“学生选课流程”，发布时间为 2019-04-19，可直接打开具体事项页面查看。",
        "source": "https://jwc.jnu.edu.cn/2019/0419/c11805a310286/page.htm",
        "keywords": "选课, 学生选课流程, 课程选择, 学生办事指南",
    },
    {
        "filename": "暑期课程选课缴费.md",
        "title": "暑期课程选课与缴费",
        "category": "考试选课",
        "department": "本科生院",
        "answer": "2026 年暑期课程选课与缴费通知在暨南大学本科生院通知栏目中，选课时间为 2026 年 7 月 8 日 10:00 至 7 月 13 日 10:00，缴费时间为 7 月 13 日 15:00 至 7 月 15 日 15:00。",
        "source": "https://jwc.jnu.edu.cn/2026/0707/c6765a859020/page.htm",
        "keywords": "暑期课程, 暑期班, 选课, 缴费, 自助缴费平台, 财务大厅",
    },
    {
        "filename": "推免申请报名.md",
        "title": "推免申请报名",
        "category": "升学保研",
        "department": "本科生院",
        "answer": "2027 届本科毕业生（内招生）推免申请通知在暨南大学本科生院通知栏目中，申请时间为 2026 年 7 月 14 日至 9 月 2 日 12:00，符合条件的内招学生需在规定时间内报名。",
        "source": "https://jwc.jnu.edu.cn/2026/0713/c6765a860093/page.htm",
        "keywords": "推免, 保研, 免初试, 研究生, 2027届, 内招生, 推免申请",
    },
    {
        "filename": "交换生学分转换申请表.md",
        "title": "交换生学分转换申请表",
        "category": "学籍",
        "department": "本科生院",
        "answer": "交换生学分转换申请表在暨南大学本科生院“下载服务 - 学籍相关文件”栏目中，材料名称为“JH2_交换生学分转换申请表”，发布时间为 2021-03-13，可直接打开具体事项页面下载。",
        "source": "https://jwc.jnu.edu.cn/2021/0313/c6757a601007/page.htm",
        "keywords": "交换生, 学分转换, JH2, 交换生学分转换申请表, 学籍相关文件",
    },
    {
        "filename": "本科生毕业实习流程.md",
        "title": "本科生毕业实习工作流程",
        "category": "实习实践",
        "department": "本科生院",
        "answer": "本科生毕业实习工作流程说明在暨南大学本科生院“学生办事指南”栏目中，事项名称为“本科生毕业实习工作流程”，发布时间为 2019-04-19，可直接打开具体事项页面查看。",
        "source": "https://jwc.jnu.edu.cn/2019/0419/c11805a310288/page.htm",
        "keywords": "毕业实习, 本科生毕业实习, 实习流程, 学生办事指南",
    },
    {
        "filename": "创新学分申请表.md",
        "title": "创新学分申请表",
        "category": "实习实践",
        "department": "本科生院",
        "answer": "创新学分申请表在暨南大学本科生院“下载服务 - 实践教学文件”栏目中，材料名称为“创新学分申请表（2个）”，发布时间为 2021-03-13，可直接打开具体事项页面下载。",
        "source": "https://jwc.jnu.edu.cn/2021/0313/c6758a601063/page.htm",
        "keywords": "创新学分, 创新学分申请表, 实践教学文件, 本科生院",
    },
    {
        "filename": "实践教育基地协议模板.md",
        "title": "实践教育基地协议模板",
        "category": "实习实践",
        "department": "本科生院",
        "answer": "暨南大学实践教育基地协议模板在暨南大学本科生院“下载服务 - 实践教学文件”栏目中，材料名称为“暨南大学实践教育基地协议（模板）”，文件名为“模板-暨南大学实践教育基地协议.docx”，可直接打开具体事项页面下载。",
        "source": "https://jwc.jnu.edu.cn/2023/1031/c6758a770877/page.htm",
        "keywords": "实践教育基地, 实践基地协议, 协议模板, 实践教学文件, docx",
    },
    {
        "filename": "新生个人信息勘误申请表.md",
        "title": "本科学生个人信息勘误申请表",
        "category": "新生",
        "department": "招生办公室",
        "answer": "本科学生个人信息勘误申请表在暨南大学招生办公室“下载中心”栏目中，材料名称为“暨南大学本科学生个人信息勘误申请表”，发布时间为 2022-04-05，可直接打开具体事项页面下载。",
        "source": "https://zsb.jnu.edu.cn/2022/0405/c3464a688765/page.htm",
        "keywords": "新生, 个人信息勘误, 信息修改, 本科学生个人信息勘误申请表, 下载中心",
    },
    {
        "filename": "来粤留学生奖学金申请表.md",
        "title": "广东省政府来粤留学生奖学金申请表",
        "category": "奖助学金",
        "department": "招生办公室",
        "answer": "广东省政府来粤留学生奖学金申请表在暨南大学招生办公室“下载中心”栏目中，材料名称为“广东省政府来粤留学生奖学金申请表（本科新生）”，发布时间为 2019-04-09，可直接打开具体事项页面下载。",
        "source": "https://zsb.jnu.edu.cn/2019/0409/c3464a308704/page.htm",
        "keywords": "奖学金, 来粤留学生奖学金, 本科新生, 广东省政府, 下载中心",
    },
    {
        "filename": "丝路奖学金申请表.md",
        "title": "暨南大学丝路奖学金申请表",
        "category": "奖助学金",
        "department": "招生办公室",
        "answer": "暨南大学招生办公室下载中心仍列有“暨南大学丝路奖学金申请表”（2016-04-21），但原附件直链当前返回 403，无法作为可靠公开下载通道；请从招生办公室下载中心查看最新材料或联系招生办公室确认。",
        "source": "https://zsb.jnu.edu.cn/3562/list2.htm",
        "discover_downloads": False,
        "keywords": "奖学金, 丝路奖学金, 暨南大学丝路奖学金申请表, 招生办公室, 下载中心",
    },
    {
        "filename": "校本部番禺校区教学班车时间.md",
        "title": "校本部与番禺校区教学班车时间",
        "category": "交通出行",
        "department": "番禺校区管理委员会",
        "answer": "校本部与番禺校区教学班车时间属于信息查询事项。2025—2026 学年第二学期班车时刻表自 2026 年 3 月 9 日起执行。周一至周五：校本部到番禺校区 7:30、8:00、8:30、9:30、13:00、15:00、16:00、17:20、18:30、20:30、21:15；番禺校区到校本部 8:40、9:20、10:30、13:00、14:20、16:00、17:10、18:00、19:30、20:50、21:30。周六周日：校本部到番禺校区 7:30、8:30、9:30、13:00、17:20；番禺校区到校本部 8:40、13:00、17:10、18:30、21:15。校本部乘车点为行政办公楼北侧候车点，番禺校区乘车点为教学楼北侧候车亭。节假日、考试周与暑假期间时刻表另行公布。",
        "source": "https://panyu.jnu.edu.cn/jtzn/list.htm",
        "keywords": "校巴, 校车, 班车, 教学班车, 校本部, 番禺校区, 交通指南, 发车时间, 校巴时间",
    },
    {
        "filename": "暨南大学校历查询.md",
        "title": "暨南大学校历查询",
        "category": "校历",
        "department": "暨南大学 / 本科生院",
        "answer": "暨南大学校历可在学校主页“校历”页面查询，页面提供 2026-2027 学年校历和 2025-2026 学年校历 PDF；本科生院“暨大校历”栏目也提供 2025-2026 学年校历 PDF。",
        "source": "https://www.jnu.edu.cn/2022/0829/c36421a714341/page.htm",
        "keywords": "校历, 学年校历, 开学时间, 放假时间, 寒假, 暑假, 教学周, 2025-2026, 2026-2027",
    },
    {
        "filename": "校园网学生申请.md",
        "title": "校园网服务申请（学生）",
        "category": "网络服务",
        "department": "网络与教育技术中心",
        "answer": "暨南大学学生校园网可通过校园网用户自助服务平台在线办理，也可通过校园卡圈存机自助办理。服务对象为全校在校学生；单终端资费为 15 元/月、150 元/年，双终端资费为 30 元/月、300 元/年；受理时间为全年受理，办理时限为 1 个工作日。服务热线：020-85220304、020-85220305。",
        "source": "https://netc.jnu.edu.cn/2018/1205/c9830a268227/page.psp",
        "keywords": "校园网, 校园网申请, 上网账号, mynet, 网络缴费, 无线网络, 有线网络, 网络与教育技术中心",
    },
    {
        "filename": "图书续借和预约.md",
        "title": "图书续借和预约",
        "category": "图书馆",
        "department": "图书馆",
        "answer": "图书续借可登录图书馆主页，在“我的图书馆—图书借阅（我的借阅）—当前借阅”中点击续借；逾期或已被他人预约的图书不能续借。预约图书可在图书馆检索到馆藏后点击“预约”，预约成功后可在“我的预约”查看状态；预约书保留 5 天。",
        "source": "https://zhlib.jnu.edu.cn/wtsxjhyy/list.htm",
        "keywords": "图书馆, 图书续借, 图书预约, 我的图书馆, 借阅, 预约书, 借书, 还书",
    },
    {
        "filename": "校园卡充值.md",
        "title": "校园卡充值",
        "category": "校园卡",
        "department": "网络与教育技术中心",
        "answer": "校园卡可线上或线下充值。线上可使用支付宝：打开支付宝，进入“大学生活”，点击“一卡通”，输入校园卡信息和充值金额后确认充值，之后前往校内 POS 机消费即可到账。线下可通过圈存机绑定银行卡自助充值，也可前往各校区现金充值点办理。",
        "source": "https://netc.jnu.edu.cn/cjwd_9907/list.htm",
        "keywords": "校园卡, 一卡通, 充值, 支付宝充值, 圈存机, 校园卡余额, 校园卡限额",
    },
    {
        "filename": "番禺校区食堂营业时间.md",
        "title": "番禺校区食堂营业时间",
        "category": "餐饮服务",
        "department": "番禺校区 / 外国语学院",
        "answer": "番禺校区公开新生攻略中列出的常规餐饮时间包括：裕华堂第一食堂一楼早餐 06:30-09:00、午餐 10:30-13:30、晚餐 16:30-19:00；暨南苑二楼早餐 06:30-08:30、午餐 10:30-13:00、晚餐/宵夜 16:30-22:30；暨香苑三楼早餐 07:30-09:30、午餐 10:30-13:00、晚餐 16:30-18:30；弘礼餐厅午餐 11:40-13:00、晚餐/宵夜 17:00-22:30；湖景餐厅午餐 10:30-13:00、晚餐 16:30-18:30。寒暑假、节假日和临时调整以校区通知或现场公告为准。",
        "source": "https://fc.jnu.edu.cn/2026/0330/c33807a852624/page.htm",
        "keywords": "食堂, 饭堂, 餐厅, 营业时间, 开门时间, 几点开门, 食堂几点, 饭堂几点, 早餐, 午餐, 晚餐, 宵夜, 番禺校区, 裕华堂, 弘礼餐厅, 湖景餐厅",
    },
    {
        "filename": "本科生休学流程.md",
        "title": "本科生办理休学流程",
        "category": "学籍",
        "department": "本科生院",
        "answer": "本科生办理休学时，学生填写休学申请表；因病休学须经校门诊核签。申请表交学院教科办，学院审批并签署意见后交教务处学籍科；教务处审核批准后约 5 个工作日发出休学通知，学生凭通知回学院办理离校手续。",
        "source": "https://jwc.jnu.edu.cn/2019/0418/c11805a310056/page.htm",
        "keywords": "休学, 休学流程, 休学申请, 因病休学, 学籍科, 离校手续, 本科生",
    },
    {
        "filename": "本科生复学流程.md",
        "title": "本科生办理复学流程",
        "category": "学籍",
        "department": "本科生院",
        "answer": "本科生休学期满，应于学期开学前到学院教科办填写复学申请表；因病休学者须经校门诊体检并凭证明办理。学院审批后交教务处学籍科；教务处审查符合复学条件后开出复学通知。学生领取复学通知后，到财务处交学费，再到学院注册并办理选课事宜。",
        "source": "https://jwc.jnu.edu.cn/2019/0418/c11805a310075/page.htm",
        "keywords": "复学, 复学流程, 复学申请, 休学期满, 学籍科, 注册, 选课, 本科生",
    },
    {
        "filename": "本科生退学流程.md",
        "title": "本科生办理退学流程",
        "category": "学籍",
        "department": "本科生院",
        "answer": "本科生申请退学时，将书面申请交学院教务秘书处，并在教务秘书指导下填写《暨南大学本科学生退学申请表》。学院审批后交教务处学籍科；经教务处审核并报校长办公会批准后，学校发文并通知学院。学院通知学生按离校清单办理离校手续，办完后到教务处学籍科办理相应退学证明。",
        "source": "https://jwc.jnu.edu.cn/2019/0418/c11805a310100/page.htm",
        "keywords": "退学, 退学流程, 退学申请, 退学申请表, 离校手续, 退学证明, 学籍科, 本科生",
    },
    {
        "filename": "研究生服务中心业务办理.md",
        "title": "研究生服务中心业务办理",
        "category": "研究生事务",
        "department": "研究生院",
        "answer": "暨南大学研究生教育服务中心面向研究生和校友提供一站式服务，主要受理培养、学位等咨询和材料接收，可办理研究生在读证明、出国成绩单、学位证明、学历学位认证、补办学位证明书、学历证明书、研究生证和火车票优惠卡等事项。",
        "source": "https://gs.jnu.edu.cn/yjsfwzx/list.htm",
        "keywords": "研究生服务中心, 研究生在读证明, 出国成绩单, 学位证明, 学历学位认证, 研究生证, 火车票优惠卡, 研究生事务",
    },
    {
        "filename": "毕业生就业手续入口.md",
        "title": "毕业生就业手续入口",
        "category": "就业档案",
        "department": "就业指导中心",
        "answer": "暨南大学学生就业指导中心网站提供毕业生相关入口，包括就业信息、校内外宣讲会、双选会、在线招聘、公务员招考、实习岗位、就业指导、三方协议、报到证、就业信息填写、调整改派、常用下载和档案查询等栏目。",
        "source": "https://career.jnu.edu.cn/",
        "keywords": "就业, 就业手续, 三方协议, 报到证, 档案查询, 就业信息填写, 调整改派, 招聘, 实习岗位, 毕业生",
    },
    {
        "filename": "公费医疗服务指南.md",
        "title": "公费医疗服务指南",
        "category": "医保医疗",
        "department": "公费医疗办公室",
        "answer": "暨南大学公费医疗办公室网站提供校内公费医疗相关通知和服务指南；学生涉及医保、公费医疗、门诊、住院或报销类问题时，应优先查看公费医疗办公室“服务指南”栏目，并以页面最新说明为准。",
        "source": "https://gyb.jnu.edu.cn/9256/list6.htm",
        "keywords": "医保, 公费医疗, 服务指南, 门诊, 住院, 报销, 医疗, 校医院, 学生医保",
    },
]


def service_type(card: dict) -> str:
    if card.get("service_type"):
        return card["service_type"]
    filename = card["filename"]
    title = card["title"]
    if card["category"] in {"交通出行", "校历", "通知公告", "餐饮服务"}:
        return "信息查询"
    if card["category"] in {"网络服务", "图书馆", "校园卡"}:
        return "办事流程"
    if "流程" in title or "缴费" in title or "报名" in title or "补办" in title:
        return "办事流程"
    if card["category"] in {"研究生事务", "就业档案", "医保医疗"}:
        return "办事指引"
    if "表" in title or "模板" in title:
        return "表格模板"
    return "办事指引"


def entrance(card: dict) -> str:
    if card.get("entrance"):
        return card["entrance"]
    source = card["source"]
    title = card["title"]
    category = card["category"]
    if category == "交通出行":
        return "暨南大学番禺校区“服务指南 - 实用信息 - 交通指南”栏目"
    if category == "校历":
        return "暨南大学主页“校历”页面"
    if category == "网络服务":
        return "暨南大学网络与教育技术中心“办事流程 - 校园网络”栏目"
    if category == "图书馆":
        return "暨南大学图书馆“服务 - 图书借阅”栏目"
    if category == "校园卡":
        return "暨南大学网络与教育技术中心常见问答"
    if category == "餐饮服务":
        return "暨南大学官方学院/校区公开生活服务页面"
    if category == "研究生事务":
        return "暨南大学研究生院研究生服务中心栏目"
    if category == "就业档案":
        return "暨南大学学生就业指导中心网站"
    if category == "医保医疗":
        return "暨南大学公费医疗办公室服务指南栏目"
    if "补办" in title or "流程" in title or "成绩单" in title or "在学证明" in title:
        return "暨南大学本科生院“学生办事指南”栏目"
    if category in {"请假", "转专业", "学籍", "成绩证明"} and card["department"] == "本科生院":
        return "暨南大学本科生院“下载服务 - 学籍相关文件”栏目"
    if category == "实习实践":
        return "暨南大学本科生院“下载服务 - 实践教学文件”栏目"
    if card["department"] == "招生办公室":
        return "暨南大学招生办公室“下载中心”栏目"
    if "jwc.jnu.edu.cn/2026/0707" in source:
        return "暨南大学本科生院通知栏目"
    if "jwc.jnu.edu.cn/2026/0713" in source:
        return "暨南大学本科生院通知栏目"
    return "来源页面"


def audience(card: dict) -> str:
    text = f'{card["title"]} {card["answer"]} {card["keywords"]}'
    if card["category"] == "交通出行":
        return "需要往返校区或查询交通信息的师生"
    if card["category"] in {"校历", "网络服务", "图书馆", "校园卡", "餐饮服务"}:
        return "需要查询校园公共服务的师生"
    if card["category"] == "研究生事务":
        return "暨南大学研究生或校友"
    if card["category"] == "就业档案":
        return "暨南大学毕业生或求职学生"
    if card["category"] == "医保医疗":
        return "需要办理医疗、医保或报销事项的师生"
    if "新生" in text:
        return "本科新生或相关申请人"
    if "全日制本科" in text:
        return "在校全日制本科学生"
    if "本科" in text or card["department"] == "本科生院":
        return "暨南大学本科学生"
    return "相关学生"


def materials(card: dict) -> str:
    if card.get("materials"):
        return card["materials"]
    title = card["title"]
    answer = card["answer"]
    if card["category"] == "交通出行":
        return "校本部与番禺校区教学班车时刻表"
    if card["category"] == "校历":
        return "学年校历 PDF"
    if card["category"] == "网络服务":
        return "校园网服务申请信息"
    if card["category"] == "图书馆":
        return "图书续借和预约说明"
    if card["category"] == "校园卡":
        return "校园卡充值说明"
    if card["category"] == "餐饮服务":
        return "番禺校区食堂和餐厅营业时间"
    if card["category"] == "研究生事务":
        return "研究生服务中心业务办理说明"
    if card["category"] == "就业档案":
        return "毕业生就业手续相关栏目"
    if card["category"] == "医保医疗":
        return "公费医疗办公室服务指南"
    if "可见" in answer:
        return answer.split("可见", 1)[1].split("，发布时间", 1)[0].strip("“”\"'。”.")
    if "材料名称为" in answer:
        return answer.split("材料名称为", 1)[1].split("，", 1)[0].strip("“”\"'。”.")
    if "事项名称为" in answer:
        return answer.split("事项名称为", 1)[1].split("，", 1)[0].strip("“”\"'。”.")
    return title


def steps(card: dict) -> list[str]:
    if card["category"] == "交通出行":
        return [
            f"打开{entrance(card)}。",
            "查看“教学班车”或“公交车暨南大学至新造地铁站直达专线”部分。",
            "如遇节假日、考试周、暑假或临时调整，以来源页面最新通知为准。",
        ]
    if card["category"] in {"校历", "网络服务", "图书馆", "校园卡", "餐饮服务"}:
        return [
            f"打开{entrance(card)}。",
            f"查找“{materials(card)}”相关信息。",
            "按来源页面中的最新说明办理或查询。",
        ]
    return [
        f"打开{entrance(card)}。",
        f"查找“{materials(card)}”。",
        "按来源页面或下载材料中的最新要求办理。",
    ]


def notes(card: dict) -> list[str]:
    if card["category"] == "交通出行":
        return [
            "节假日、考试周与暑假期间的班车时刻表另行公布。",
            "校本部乘车地点为行政办公楼北侧候车点，番禺校区乘车地点为教学楼北侧候车亭。",
            "教学班车主要服务教学科研安排，学生乘坐规则请以来源页面说明为准。",
        ]
    if card["category"] == "餐饮服务":
        return [
            "寒暑假、节假日、考试周和临时调整期间，餐饮时间可能变化。",
            "食堂开门时间建议以校区通知、现场公告或餐饮服务中心最新说明为准。",
            "当前卡片收录的是公开页面中可确认的常规/新生攻略信息。",
        ]
    return [
        "当前知识库只收录公开页面中可确认的信息。",
        "具体办理地点、审核要求或补充材料若未在来源中明确，请以学校来源页面为准。",
    ]


def is_official_url(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    return hostname == "jnu.edu.cn" or hostname.endswith(".jnu.edu.cn")


def download_name(url: str, link_text: str, fallback: str) -> str:
    text = " ".join(link_text.split()).strip()
    if text:
        return text
    filename = unquote(PurePosixPath(urlparse(url).path).name)
    return filename or fallback


def discover_downloads(card: dict) -> list[dict[str, str]]:
    if card.get("discover_downloads") is False:
        return []
    source = card["source"]
    source_suffix = Path(urlparse(source).path).suffix.lower()
    if source_suffix in DOWNLOAD_SUFFIXES and is_official_url(source):
        return [{"name": download_name(source, "", materials(card)), "url": source}]

    try:
        response = requests.get(source, headers=REQUEST_HEADERS, timeout=15)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding
    except requests.RequestException as exc:
        print(f"Warning: could not inspect downloads for {card['title']}: {exc}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    downloads: list[dict[str, str]] = []
    seen: set[str] = set()
    for link in soup.select("a[href]"):
        url = urljoin(source, link.get("href", "").strip())
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix not in DOWNLOAD_SUFFIXES or not is_official_url(url) or url in seen:
            continue
        seen.add(url)
        downloads.append(
            {
                "name": download_name(url, link.get_text(" ", strip=True), materials(card)),
                "url": url,
            }
        )
    return downloads


def main() -> None:
    CARD_DIR.mkdir(parents=True, exist_ok=True)
    for old in CARD_DIR.glob("*.md"):
        old.unlink()
    for card in CARDS:
        step_block = "\n".join(f"{idx}. {step}" for idx, step in enumerate(steps(card), start=1))
        note_block = "\n".join(f"- {note}" for note in notes(card))
        downloads = discover_downloads(card)
        download_block = ""
        if downloads:
            download_lines = "\n".join(f'- {item["name"]} | {item["url"]}' for item in downloads)
            download_block = f"\n下载文件：\n{download_lines}\n"
        body = f"""# {card["title"]}

类别：{card["category"]}

事项类型：{service_type(card)}

负责部门：{card["department"]}

适用对象：{audience(card)}

办理入口：{entrance(card)}

所需材料：{materials(card)}

直接回答：{card["answer"]}

办理步骤：
{step_block}

注意事项：
{note_block}
{download_block}

来源链接：{card["source"]}

关键词：{card["keywords"]}
"""
        (CARD_DIR / card["filename"]).write_text(body, encoding="utf-8")
    print(f"Generated {len(CARDS)} service cards: {CARD_DIR}")


if __name__ == "__main__":
    main()
