import json
import os
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, redirect, render_template, request, session, url_for

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "demo-secret-key-2026")


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


def generate_study_plan(exam_date_str, daily_hours, weak_topics_raw):
    exam_date = parse_exam_date(exam_date_str)
    days_left = max((exam_date.date() - datetime.today().date()).days, 7)
    days = min(days_left, 14)
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
        "percent": 88,
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
            ("真实 OCR 拍照识别", False),
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
        session["plan"] = generate_study_plan(
            profile["exam_date"],
            profile["daily_hours"],
            profile["weak_topics"],
        )
        session["wrong_questions"] = []
        return redirect(url_for("index"))

    profile = session.get("profile")
    plan = session.get("plan", [])
    wrong_questions = session.get("wrong_questions", [])
    weak_topics = split_topics(profile["weak_topics"]) if profile else []

    return render_template(
        "index.html",
        defaults=DEFAULT_PROFILE,
        profile=profile,
        plan=plan,
        wrong_questions=wrong_questions,
        summary=build_summary(plan, wrong_questions),
        active_reminder=get_active_reminder(plan, wrong_questions),
        weak_topic_scores=calculate_weak_index(weak_topics, wrong_questions),
        review_schedule=build_review_schedule(wrong_questions),
        intro_completion=completion_against_intro(),
        error_types=list(ERROR_HINTS.keys()),
        llm_enabled=get_openai_client() is not None,
        openai_model=OPENAI_MODEL,
        openai_base_url=OPENAI_BASE_URL,
        login_name=session.get("login_name"),
    )


@app.route("/wrong", methods=["POST"])
@login_required
def wrong():
    question = request.form.get("question", "").strip()
    error_type = request.form.get("error_type", "概念不清")
    knowledge_point = request.form.get("knowledge_point", "页面置换算法").strip()
    wrong_questions = session.get("wrong_questions", [])
    wrong_questions.append(analyze_wrong_question(question, error_type, knowledge_point))
    session["wrong_questions"] = wrong_questions
    return redirect(url_for("index"))


@app.route("/wrong/<int:index>/delete", methods=["POST"])
@login_required
def delete_wrong(index):
    wrong_questions = session.get("wrong_questions", [])
    if 0 <= index < len(wrong_questions):
        wrong_questions.pop(index)
        session["wrong_questions"] = wrong_questions
    return redirect(url_for("index"))


@app.route("/toggle/<int:day>", methods=["POST"])
@login_required
def toggle_task(day):
    plan = session.get("plan", [])
    for item in plan:
        if item["day"] == day:
            item["completed"] = not item.get("completed", False)
            break
    session["plan"] = plan
    return redirect(url_for("index"))


@app.route("/reset")
@login_required
def reset():
    session.pop("profile", None)
    session.pop("plan", None)
    session.pop("wrong_questions", None)
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
