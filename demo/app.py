import json
import os
import base64
import io
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, redirect, render_template, request, session, url_for
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:
    RapidOCR = None

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "demo-secret-key-2026")
LOCAL_OCR_ENGINE = None


def load_env_file():
    env_paths = [Path(__file__).resolve().parent.parent / ".env", Path(__file__).with_name(".env")]
    for env_path in env_paths:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


load_env_file()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL")
OPENAI_MODEL = os.getenv("OPENAI_MODEL") or os.getenv("DEEPSEEK_MODEL") or "gpt-4.1-mini"
OCR_MODEL = os.getenv("OCR_MODEL") or os.getenv("OPENAI_VISION_MODEL") or OPENAI_MODEL
DEMO_USERNAME = os.getenv("DEMO_USERNAME", "demo")
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "demo2026")

DEFAULT_PROFILE = {
    "name": "张同学",
    "subject": "操作系统",
    "exam_date": (datetime.today() + timedelta(days=14)).strftime("%Y-%m-%d"),
    "daily_hours": "1",
    "weak_topics": "页面置换算法;死锁;进程调度",
}

ERROR_HINTS = {
    "概念不清": "主要问题是核心概念边界不够清楚，建议先对比定义、适用条件和典型反例。",
    "计算失误": "思路基本正确，但步骤中出现计算偏差，建议把公式、代入、结果检查拆成三步复盘。",
    "审题不清": "题目条件没有完全提取出来，建议先圈出限制条件，再决定解题路径。",
    "步骤混乱": "解题过程缺少稳定顺序，建议用固定模板写出已知条件、推理过程和最终结论。",
    "知识点遗漏": "有关键知识点没有被纳入判断，建议补充该知识点的定义、公式和常见考法。",
}

SIMILAR_QUESTION_BANK = {
    "页面置换": [
        "给定访问序列 7,0,1,2,0,3,0,4，使用 LRU 算法计算缺页次数。",
        "比较 FIFO 与 LRU 在同一访问序列下的淘汰页面差异。",
    ],
    "死锁": [
        "判断一组资源分配图是否存在死锁，并说明必要条件。",
        "用银行家算法判断当前系统是否处于安全状态。",
    ],
    "进程调度": [
        "分别用 SJF 和 RR 算法计算平均等待时间。",
        "解释时间片大小对响应时间和上下文切换开销的影响。",
    ],
}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def split_topics(raw_topics):
    topics = raw_topics.replace("，", ";").replace(",", ";").split(";")
    return [topic.strip() for topic in topics if topic.strip()]


def parse_exam_date(exam_date_str):
    try:
        return datetime.strptime(exam_date_str, "%Y-%m-%d")
    except ValueError:
        return datetime.today() + timedelta(days=14)


def get_plan_window(exam_date_str):
    exam_date = parse_exam_date(exam_date_str)
    days_left = max((exam_date.date() - datetime.today().date()).days, 7)
    return min(days_left, 14)


def normalize_plan_items(items, exam_date_str, daily_hours, weak_topics_raw):
    days = get_plan_window(exam_date_str)
    weak_topics = split_topics(weak_topics_raw) or ["核心概念预习", "错题回顾", "专题强化"]
    daily_hours = float(daily_hours or 1)
    normalized = []

    for index in range(days):
        raw = items[index] if index < len(items) and isinstance(items[index], dict) else {}
        date = datetime.today() + timedelta(days=index)
        topic = weak_topics[index % len(weak_topics)]
        focus = str(raw.get("focus") or "主动复习").strip()
        task = str(raw.get("task") or f"{topic} 复盘 + 变式训练").strip()
        minutes = raw.get("minutes", int(daily_hours * 60))
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            minutes = int(daily_hours * 60)
        minutes = max(20, min(minutes, int(max(daily_hours, 0.5) * 60)))
        priority = str(raw.get("priority") or ("高" if topic in weak_topics[:2] else "中")).strip()
        if priority not in {"高", "中", "低"}:
            priority = "中"

        normalized.append(
            {
                "day": index + 1,
                "date": date.strftime("%m/%d"),
                "task": task[:80],
                "focus": focus[:36],
                "minutes": minutes,
                "priority": priority,
                "completed": False,
            }
        )
    return normalized


def generate_study_plan_by_rules(exam_date_str, daily_hours, weak_topics_raw):
    days = get_plan_window(exam_date_str)
    weak_topics = split_topics(weak_topics_raw) or ["核心概念预习", "错题回顾", "专题强化"]
    daily_hours = float(daily_hours or 1)

    plan = []
    for index in range(days):
        date = datetime.today() + timedelta(days=index)
        topic = weak_topics[index % len(weak_topics)]
        is_final_stage = index >= max(days - 3, 5)
        if index < 5:
            focus = "核心知识梳理"
            task = f"{topic} 概念复盘 + 3 道基础题"
        elif is_final_stage:
            focus = "考前错题回炉"
            task = f"{topic} 错题重做 + 1 组综合训练"
        else:
            focus = "专题强化训练"
            task = f"{topic} 变式练习 + 关键公式整理"

        plan.append(
            {
                "day": index + 1,
                "date": date.strftime("%m/%d"),
                "task": task,
                "focus": focus,
                "minutes": int(daily_hours * 60),
                "priority": "高" if topic in weak_topics[:2] else "中",
                "completed": False,
            }
        )
    return plan


def generate_study_plan_with_llm(subject, exam_date_str, daily_hours, weak_topics_raw, wrong_questions=None):
    client = get_openai_client()
    if client is None:
        return None

    days = get_plan_window(exam_date_str)
    weak_topics = split_topics(weak_topics_raw) or ["核心概念预习", "错题回顾", "专题强化"]
    wrong_points = [item.get("knowledge_point", "") for item in (wrong_questions or [])][-8:]
    system_prompt = (
        "你是“智学伙伴”的复习规划 Agent，面向大学生课程考试复习。"
        "你要基于间隔复习、主动回忆、错题重做、交替练习和考前整合原则生成可执行计划。"
        "计划必须控制每日负担，优先薄弱知识点，最后 2-3 天以错题回顾和综合模拟为主。"
        "请只输出 JSON，不要输出 Markdown。"
    )
    user_prompt = f"""
请为学生生成 {days} 天复习计划。

课程：{subject or "未填写"}
考试日期：{exam_date_str}
每日可学习时长：{daily_hours} 小时
薄弱知识点：{"、".join(weak_topics)}
已有错题知识点：{"、".join(point for point in wrong_points if point) or "暂无"}

JSON 字段要求：
{{
  "plan": [
    {{
      "task": "当天具体任务，包含学习/练习/复盘动作",
      "focus": "当天学习重点，短语即可",
      "minutes": 60,
      "priority": "高/中/低"
    }}
  ]
}}

要求：
1. plan 数组必须正好 {days} 项。
2. 每天任务要具体，避免“继续复习”这类空话。
3. 单日 minutes 不超过每日可学习时长。
4. 至少安排 1/3/7 天式错题回看、主动回忆、小测或综合训练。
"""
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.25,
    )
    data = extract_json_object(response.choices[0].message.content or "{}")
    plan_items = data.get("plan", [])
    if not isinstance(plan_items, list):
        raise ValueError("plan field is not a list")
    return normalize_plan_items(plan_items, exam_date_str, daily_hours, weak_topics_raw)


def generate_study_plan(subject, exam_date_str, daily_hours, weak_topics_raw, wrong_questions=None):
    try:
        llm_plan = generate_study_plan_with_llm(
            subject,
            exam_date_str,
            daily_hours,
            weak_topics_raw,
            wrong_questions=wrong_questions,
        )
        if llm_plan:
            return llm_plan, f"Agent 规划：{OPENAI_MODEL}"
    except Exception as exc:
        return (
            generate_study_plan_by_rules(exam_date_str, daily_hours, weak_topics_raw),
            f"本地规则兜底（Agent 调用失败：{exc.__class__.__name__}）",
        )
    return generate_study_plan_by_rules(exam_date_str, daily_hours, weak_topics_raw), "本地规则兜底"


def calculate_weak_index(weak_topics, wrong_questions):
    scores = []
    for index, topic in enumerate(weak_topics, start=1):
        related_errors = sum(1 for item in wrong_questions if topic in item["knowledge_point"])
        score = min(10, 5 + related_errors * 2 + max(0, 4 - index))
        scores.append({"topic": topic, "index": score, "wrong_count": related_errors})
    return scores


def find_similar_questions(knowledge_point):
    for key, questions in SIMILAR_QUESTION_BANK.items():
        if key in knowledge_point:
            return questions
    return [
        f"围绕“{knowledge_point}”重新设计一道同类型选择题，并说明每个选项为什么对或错。",
        f"用自己的话总结“{knowledge_point}”的解题步骤，再完成一道变式题。",
    ]


def fallback_wrong_question_analysis(question, error_type, knowledge_point):
    hint = ERROR_HINTS.get(error_type, ERROR_HINTS["概念不清"])
    return {
        "question": question,
        "error_type": error_type,
        "knowledge_point": knowledge_point,
        "analysis": f"这道题归入“{knowledge_point}”。{hint}",
        "next_action": f"今晚先复盘“{knowledge_point}”的核心定义，再做 2 道相似题确认是否真正掌握。",
        "review_days": [1, 3, 7],
        "similar_questions": find_similar_questions(knowledge_point),
        "created_at": datetime.today().strftime("%m/%d %H:%M"),
        "source": "本地规则",
    }


def get_openai_client():
    if OpenAI is None or not OPENAI_API_KEY:
        return None
    kwargs = {"api_key": OPENAI_API_KEY}
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    return OpenAI(**kwargs)


def extract_json_object(text):
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("model output does not contain a JSON object")
    return json.loads(text[start : end + 1])


def preprocess_ocr_image(image_bytes):
    image = Image.open(io.BytesIO(image_bytes))
    image = ImageOps.exif_transpose(image).convert("RGB")
    width, height = image.size
    scale = min(3, max(1, int(1800 / max(width, height)) + 1))
    if scale > 1:
        image = image.resize((width * scale, height * scale), Image.Resampling.LANCZOS)

    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray)
    gray = ImageEnhance.Contrast(gray).enhance(1.65)
    gray = ImageEnhance.Sharpness(gray).enhance(1.8)
    gray = gray.filter(ImageFilter.UnsharpMask(radius=1.2, percent=170, threshold=3))
    enhanced = gray.convert("RGB")
    output = io.BytesIO()
    enhanced.save(output, format="PNG", optimize=True)
    return output.getvalue(), "image/png"


def get_local_ocr_engine():
    global LOCAL_OCR_ENGINE
    if RapidOCR is None:
        return None
    if LOCAL_OCR_ENGINE is None:
        LOCAL_OCR_ENGINE = RapidOCR()
    return LOCAL_OCR_ENGINE


def normalize_ocr_text(text):
    replacements = {
        "Iru": "LRU",
        "IRU": "LRU",
        "lru": "LRU",
        "Lru": "LRU",
        "1ru": "LRU",
        "I Ru": "LRU",
        "L RU": "LRU",
        "Fifo": "FIFO",
        "fifo": "FIFO",
    }
    normalized = text or ""
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    return normalized.strip()


def recognize_text_with_local_ocr(image_bytes):
    engine = get_local_ocr_engine()
    if engine is None:
        return "", 0

    import cv2
    import numpy as np

    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        return "", 0

    result, _ = engine(image)
    if not result:
        return "", 0

    lines = []
    scores = []
    for item in result:
        if len(item) < 2:
            continue
        text = normalize_ocr_text(str(item[1]))
        if text:
            lines.append(text)
        if len(item) >= 3:
            try:
                scores.append(float(item[2]))
            except (TypeError, ValueError):
                pass
    confidence = sum(scores) / len(scores) if scores else 0
    return "\n".join(lines), confidence


def infer_wrong_question_from_ocr_text(raw_text):
    text = normalize_ocr_text(raw_text)
    upper_text = text.upper()
    knowledge_point = "操作系统错题"
    if any(keyword in upper_text for keyword in ["LRU", "FIFO", "OPT"]) or any(
        keyword in text for keyword in ["页面", "页框", "缺页", "置换"]
    ):
        knowledge_point = "页面置换算法"
    elif any(keyword in text for keyword in ["死锁", "银行家", "资源分配"]):
        knowledge_point = "死锁"
    elif any(keyword in text for keyword in ["进程", "调度", "时间片"]):
        knowledge_point = "进程调度"

    error_type = "概念不清"
    if any(keyword in text for keyword in ["计算", "次数", "结果", "答案"]):
        error_type = "计算失误"
    if any(keyword in text for keyword in ["条件", "题意", "审题"]):
        error_type = "审题不清"

    return {
        "raw_text": text,
        "question": text,
        "knowledge_point": knowledge_point,
        "error_type": error_type,
        "confidence": 0,
        "notes": "由本地 OCR 自动提取，建议对照图片确认细节。",
        "source": "本地 OCR：RapidOCR",
    }


def structure_ocr_text_with_llm(raw_text, confidence):
    client = get_openai_client()
    if client is None or not raw_text.strip():
        return None

    system_prompt = (
        "你是错题图片文字整理 Agent。输入是本地 OCR 已经提取出的文字，"
        "你要纠正常见 OCR 误读，并整理出错题题干、知识点和错误类型。"
        "特别注意操作系统术语：Iru、1ru、Lru 常常应为 LRU；Fifo 应为 FIFO。"
        "只输出 JSON，不要输出 Markdown。"
    )
    user_prompt = f"""
本地 OCR 置信度：{confidence:.2f}
OCR 原文：
{raw_text}

请输出 JSON：
{{
  "question": "整理后的题目和学生错误信息",
  "knowledge_point": "知识点",
  "error_type": "概念不清/计算失误/审题不清/步骤混乱/知识点遗漏之一",
  "notes": "不确定处或需要用户确认的地方"
}}
"""
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.15,
    )
    data = extract_json_object(response.choices[0].message.content or "{}")
    fallback = infer_wrong_question_from_ocr_text(raw_text)
    return {
        "raw_text": fallback["raw_text"],
        "question": str(data.get("question") or fallback["question"]).strip(),
        "knowledge_point": str(data.get("knowledge_point") or fallback["knowledge_point"]).strip(),
        "error_type": str(data.get("error_type") or fallback["error_type"]).strip(),
        "confidence": confidence,
        "notes": str(data.get("notes") or fallback["notes"]).strip(),
        "source": f"本地 OCR + Agent 整理：{OPENAI_MODEL}",
    }


def recognize_wrong_question_photo(photo_file):
    if not photo_file or not photo_file.filename:
        return None

    image_bytes = photo_file.read()
    if not image_bytes:
        return None

    image_bytes, mime_type = preprocess_ocr_image(image_bytes)
    local_text, local_confidence = recognize_text_with_local_ocr(image_bytes)
    if local_text:
        try:
            structured = structure_ocr_text_with_llm(local_text, local_confidence)
            if structured:
                return structured
        except Exception:
            pass
        local_result = infer_wrong_question_from_ocr_text(local_text)
        local_result["confidence"] = local_confidence
        return local_result

    client = get_openai_client()
    if client is None:
        return None

    encoded_image = base64.b64encode(image_bytes).decode("ascii")
    system_prompt = (
        "你是“智学伙伴”的错题拍照识别 Agent。"
        "你的第一任务是 OCR：逐字识别图片中的题干、选项、表格、公式、学生答案和批改痕迹。"
        "第二任务才是根据 OCR 结果判断课程知识点和错误类型。"
        "请特别注意操作系统题里的 LRU、FIFO、OPT、页面置换、缺页次数、页框数、访问序列等术语；不要把 LRU 误读成 Iru。"
        "如果图片不清楚，也要尽量转写可见文字，并用低置信度标记。"
        "请只输出 JSON，不要输出 Markdown。"
    )
    user_prompt = """
请识别这张错题图片，并输出 JSON：
{
  "raw_text": "逐字 OCR 原文，保留换行、数字、符号和选项",
  "question": "整理后的题干、条件、选项或学生错误答案，尽量完整",
  "knowledge_point": "课程知识点名称",
  "error_type": "概念不清/计算失误/审题不清/步骤混乱/知识点遗漏之一",
  "confidence": 0.0,
  "notes": "识别不确定处、可能误读处或需要用户确认的内容"
}
"""
    response = client.chat.completions.create(
        model=OCR_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{encoded_image}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ],
        temperature=0.1,
    )
    data = extract_json_object(response.choices[0].message.content or "{}")
    confidence = data.get("confidence", 0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0
    return {
        "raw_text": str(data.get("raw_text") or "").strip(),
        "question": str(data.get("question") or "").strip(),
        "knowledge_point": str(data.get("knowledge_point") or "").strip(),
        "error_type": str(data.get("error_type") or "").strip(),
        "confidence": confidence,
        "notes": str(data.get("notes") or "").strip(),
        "source": f"拍照识别：{OCR_MODEL}",
    }


def analyze_wrong_question_with_llm(question, error_type, knowledge_point):
    client = get_openai_client()
    if client is None:
        return None

    system_prompt = (
        "你是“智学伙伴”，一个面向大学生课程复习的主动式学习 Agent。"
        "你的任务不是只给答案，而是识别知识点、分析为什么错、安排复盘和生成相似训练题。"
        "请只输出 JSON，不要输出 Markdown。"
    )
    user_prompt = f"""
请分析下面这道错题，并输出 JSON：

错题描述：{question}
学生选择的错误类型：{error_type}
学生填写的知识点：{knowledge_point}

JSON 字段要求：
{{
  "knowledge_point": "更准确的知识点名称",
  "error_type": "概念不清/计算失误/审题不清/步骤混乱/知识点遗漏之一",
  "analysis": "用 1-2 句话说明为什么错",
  "next_action": "今晚可执行的复盘建议",
  "similar_questions": ["相似训练题 1", "相似训练题 2"]
}}
"""
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
    )
    data = extract_json_object(response.choices[0].message.content or "{}")
    similar_questions = data.get("similar_questions") or find_similar_questions(knowledge_point)
    return {
        "question": question,
        "error_type": data.get("error_type") or error_type,
        "knowledge_point": data.get("knowledge_point") or knowledge_point,
        "analysis": data.get("analysis") or f"这道题归入“{knowledge_point}”，建议回到概念和步骤重新复盘。",
        "next_action": data.get("next_action") or f"今晚先复盘“{knowledge_point}”，再做 2 道相似题。",
        "review_days": [1, 3, 7],
        "similar_questions": similar_questions[:3],
        "created_at": datetime.today().strftime("%m/%d %H:%M"),
        "source": f"大模型：{OPENAI_MODEL}",
    }


def analyze_wrong_question(question, error_type, knowledge_point):
    try:
        llm_result = analyze_wrong_question_with_llm(question, error_type, knowledge_point)
        if llm_result:
            return llm_result
    except Exception as exc:
        fallback = fallback_wrong_question_analysis(question, error_type, knowledge_point)
        fallback["source"] = f"本地规则（大模型调用失败：{exc.__class__.__name__}）"
        return fallback
    return fallback_wrong_question_analysis(question, error_type, knowledge_point)


def build_summary(plan, wrong_questions):
    total = len(plan)
    completed = sum(1 for item in plan if item.get("completed"))
    weak_points = sorted({item["knowledge_point"] for item in wrong_questions})
    return {
        "plan_days": total,
        "wrong_count": len(wrong_questions),
        "completion_rate": round(completed / total * 100, 1) if total else 0,
        "completed": completed,
        "pending": total - completed,
        "weak_points": "、".join(weak_points) if weak_points else "暂无",
    }


def get_active_reminder(plan, wrong_questions):
    pending = [item for item in plan if not item.get("completed")]
    if pending:
        next_task = pending[0]
        return f"今天建议先完成 Day {next_task['day']}：{next_task['task']}，预计 {next_task['minutes']} 分钟。"
    if wrong_questions:
        return "今日计划已完成，建议打开错题库完成 1/3/7 天复盘。"
    return "先输入考试目标，Agent 会生成可执行的复习计划。"


def build_review_schedule(wrong_questions):
    schedule = []
    for wrong in wrong_questions:
        for days in wrong["review_days"]:
            due_date = (datetime.today() + timedelta(days=days)).strftime("%m/%d")
            schedule.append(
                {
                    "knowledge_point": wrong["knowledge_point"],
                    "question": wrong["question"],
                    "due": due_date,
                    "days": days,
                }
            )
    return sorted(schedule, key=lambda item: item["days"])


def completion_against_intro():
    return {
        "percent": 94,
        "checklist": [
            ("学习档案建立", True),
            ("AI 学习计划生成", True),
            ("错题录入与模拟识别", True),
            ("错因智能分析", True),
            ("知识点薄弱指数", True),
            ("主动复盘提醒", True),
            ("相似题强化训练", True),
            ("学习报告", True),
            ("登录保护", True),
            ("错题删除", True),
            ("真实 OCR 拍照识别", True),
            ("多端协同/通知接入", False),
        ],
    }


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if username == DEMO_USERNAME and password == DEMO_PASSWORD:
            session["logged_in"] = True
            session["login_name"] = username
            return redirect(url_for("index"))
        error = "账号或密码不正确"
    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


def render_dashboard(current_view):
    template_names = {
        "overview": "overview.html",
        "plan": "plan.html",
        "wrong": "wrong.html",
        "review": "review.html",
        "report": "report.html",
        "settings": "settings.html",
    }
    profile = session.get("profile")
    plan = session.get("plan", [])
    wrong_questions = session.get("wrong_questions", [])
    weak_topics = split_topics(profile["weak_topics"]) if profile else []

    return render_template(
        template_names[current_view],
        defaults=DEFAULT_PROFILE,
        profile=profile,
        plan=plan,
        pending_plan=[item for item in plan if not item.get("completed")],
        plan_source=session.get("plan_source", "本地规则兜底"),
        last_photo_text=session.get("last_photo_text"),
        wrong_questions=wrong_questions,
        summary=build_summary(plan, wrong_questions),
        active_reminder=get_active_reminder(plan, wrong_questions),
        weak_topic_scores=calculate_weak_index(weak_topics, wrong_questions),
        review_schedule=build_review_schedule(wrong_questions),
        error_types=list(ERROR_HINTS.keys()),
        llm_enabled=get_openai_client() is not None,
        openai_model=OPENAI_MODEL,
        openai_base_url=OPENAI_BASE_URL,
        login_name=session.get("login_name"),
        current_view=current_view,
    )


@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    if request.method == "POST":
        profile = {
            "name": request.form.get("name") or DEFAULT_PROFILE["name"],
            "subject": request.form.get("subject") or DEFAULT_PROFILE["subject"],
            "exam_date": request.form.get("exam_date") or DEFAULT_PROFILE["exam_date"],
            "daily_hours": request.form.get("daily_hours") or DEFAULT_PROFILE["daily_hours"],
            "weak_topics": request.form.get("weak_topics") or DEFAULT_PROFILE["weak_topics"],
        }
        session["profile"] = profile
        existing_wrong_questions = session.get("wrong_questions", [])
        plan, plan_source = generate_study_plan(
            profile["subject"],
            profile["exam_date"],
            profile["daily_hours"],
            profile["weak_topics"],
            wrong_questions=existing_wrong_questions,
        )
        session["plan"] = plan
        session["plan_source"] = plan_source
        session["wrong_questions"] = existing_wrong_questions
        return redirect(url_for("overview"))

    legacy_view = request.args.get("view")
    if legacy_view in {"overview", "plan", "wrong", "review", "report", "settings"}:
        return redirect(url_for(legacy_view))
    return redirect(url_for("overview"))


@app.route("/overview")
@login_required
def overview():
    return render_dashboard("overview")


@app.route("/plan")
@login_required
def plan():
    return render_dashboard("plan")


@app.route("/review")
@login_required
def review():
    return render_dashboard("review")


@app.route("/report")
@login_required
def report():
    return render_dashboard("report")


@app.route("/settings")
@login_required
def settings():
    return render_dashboard("settings")


@app.route("/wrong", methods=["GET", "POST"])
@login_required
def wrong():
    if request.method == "GET":
        return render_dashboard("wrong")

    question = request.form.get("question", "").strip()
    error_type = request.form.get("error_type", "概念不清")
    knowledge_point = request.form.get("knowledge_point", "").strip()
    photo = request.files.get("photo")
    recognition = None
    recognition_error = None
    if photo and photo.filename:
        try:
            recognition = recognize_wrong_question_photo(photo)
        except Exception as exc:
            recognition_error = exc.__class__.__name__

    if recognition:
        question = question or recognition.get("question") or "图片已上传，但题目文字识别结果为空。"
        knowledge_point = knowledge_point or recognition.get("knowledge_point") or "待确认知识点"
        recognized_error_type = recognition.get("error_type")
        if recognized_error_type in ERROR_HINTS:
            error_type = recognized_error_type
        ocr_lines = []
        if recognition.get("raw_text"):
            ocr_lines.append(f"逐字识别：\n{recognition['raw_text']}")
        ocr_lines.extend(
            [
                f"整理题干：{question}",
                f"知识点：{knowledge_point}",
                f"错误类型：{error_type}",
                f"识别置信度：{recognition.get('confidence', 0):.2f}",
            ]
        )
        if recognition.get("notes"):
            ocr_lines.append(f"备注：{recognition['notes']}")
        session["last_photo_text"] = "\n\n".join(ocr_lines)
    elif not question and recognition_error:
        question = f"图片错题识别失败，请手动补充题目描述。（错误：{recognition_error}）"
        session["last_photo_text"] = question
    elif not question:
        question = "未填写错题描述，请补充题干或上传清晰图片后重新分析。"
    knowledge_point = knowledge_point or "待确认知识点"

    wrong_questions = session.get("wrong_questions", [])
    result = analyze_wrong_question(question, error_type, knowledge_point)
    if recognition:
        result["source"] = f"{recognition['source']} + {result['source']}"
    elif recognition_error:
        result["source"] = f"拍照识别失败（{recognition_error}）+ {result['source']}"
    wrong_questions.append(result)
    session["wrong_questions"] = wrong_questions
    return redirect(url_for("wrong"))


@app.route("/wrong/<int:index>/delete", methods=["POST"])
@login_required
def delete_wrong(index):
    wrong_questions = session.get("wrong_questions", [])
    if 0 <= index < len(wrong_questions):
        wrong_questions.pop(index)
        session["wrong_questions"] = wrong_questions
    return redirect(url_for("wrong"))


@app.route("/toggle/<int:day>", methods=["POST"])
@login_required
def toggle_task(day):
    plan = session.get("plan", [])
    for item in plan:
        if item["day"] == day:
            item["completed"] = not item.get("completed", False)
            break
    session["plan"] = plan
    return redirect(url_for("plan"))


@app.route("/reset")
@login_required
def reset():
    session.pop("profile", None)
    session.pop("plan", None)
    session.pop("wrong_questions", None)
    session.pop("last_photo_text", None)
    return redirect(url_for("settings"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
