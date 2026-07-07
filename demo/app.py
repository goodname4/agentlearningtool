import json
import os
import base64
import re
import random
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from io import BytesIO

from flask import Flask, redirect, render_template, request, session, url_for, jsonify

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# 可选 OCR 库
try:
    import easyocr
    OCR_AVAILABLE = True
    ocr_reader = easyocr.Reader(['ch_sim', 'en'], gpu=False)
except ImportError:
    OCR_AVAILABLE = False
    ocr_reader = None

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "demo-secret-key-2026")

# ---------------------------- 环境变量加载 ----------------------------
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

# ---------------------------- 默认数据 ----------------------------
DEFAULT_PROFILE = {
    "name": "张同学",
    "subject": "操作系统",
    "exam_date": (datetime.today() + timedelta(days=14)).strftime("%Y-%m-%d"),
    "daily_hours": "1",
    "weak_topics": "页面置换算法;死锁;进程调度",
    "ability": "一般"
}

ERROR_HINTS = {
    "概念不清": "核心概念边界模糊，建议对比定义、适用条件和反例。",
    "公式不会": "缺少公式记忆或应用能力，建议整理公式推导。",
    "步骤混乱": "解题顺序不稳定，建议固定流程。",
    "计算失误": "计算细节出错，建议分步检查。    ",
    "审题错误": "忽略关键条件，建议圈出限制条件。",
    "记忆混淆": "相似概念混淆，建议制作对比表。",
    "方法选择错误": "选错算法或策略，建议总结各类方法的适用场景。"
}

SIMILAR_QUESTION_BANK = {
    "页面置换": [
        ("基础", "给定访问序列 7,0,1,2,0,3,0,4，使用 LRU 计算缺页次数。"),
        ("中等", "比较 FIFO 与 LRU 在同一序列下的淘汰差异，并解释原因。"),
        ("综合", "设计一个访问序列使 FIFO 优于 LRU，并证明。")
    ],
    "死锁": [
        ("基础", "判断给定资源分配图是否存在死锁，说明必要条件。"),
        ("中等", "用银行家算法判断安全状态，并给出安全序列。"),
        ("综合", "设计一个死锁避免策略，评估其开销。")
    ],
    "进程调度": [
        ("基础", "SJF 与 RR 的平均等待时间计算。"),
        ("中等", "时间片大小对响应时间和切换开销的影响分析。"),
        ("综合", "多级队列调度设计，比较不同策略。")
    ]
}

# ---------------------------- 辅助函数 ----------------------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def split_topics(raw):
    raw = raw.replace("，", ";").replace(",", ";")
    return [t.strip() for t in raw.split(";") if t.strip()]

def parse_exam_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except:
        return datetime.today() + timedelta(days=14)

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
    if start == -1 or end == -1:
        raise ValueError("No JSON found")
    return json.loads(text[start:end+1])

def find_similar_questions(knowledge_point, level="中等"):
    """返回 (难度, 题目) 列表，默认中等"""
    for key, questions in SIMILAR_QUESTION_BANK.items():
        if key in knowledge_point:
            filtered = [q for q in questions if q[0] == level]
            if not filtered:
                filtered = questions
            return filtered
    return [("基础", f"围绕“{knowledge_point}”设计一道同类型题。")]

# ---------------------------- 核心业务函数 ----------------------------
def generate_study_plan(profile, completed_days=0, wrong_questions=None):
    exam_date = parse_exam_date(profile["exam_date"])
    days_left = max((exam_date.date() - datetime.today().date()).days, 7)
    total_days = min(days_left, 14)
    daily_hours = float(profile.get("daily_hours", 1))
    weak_topics = split_topics(profile.get("weak_topics", ""))
    ability = profile.get("ability", "一般")

    if ability == "薄弱":
        base_tasks_per_day = 2
    elif ability == "较好":
        base_tasks_per_day = 4
    else:
        base_tasks_per_day = 3

    error_count = {}
    if wrong_questions:
        for w in wrong_questions:
            kp = w.get("knowledge_point", "")
            if kp:
                error_count[kp] = error_count.get(kp, 0) + 1

    plan = []
    start_day = completed_days + 1
    for index in range(start_day, total_days + 1):
        sorted_topics = sorted(weak_topics, key=lambda t: -error_count.get(t, 0))
        if not sorted_topics:
            sorted_topics = ["核心概念预习", "错题回顾", "专题强化"]
        topic = sorted_topics[(index - 1) % len(sorted_topics)]
        remaining = total_days - index + 1
        if remaining <= 3:
            focus = "考前冲刺·错题回炉"
            task = f"{topic} 错题重做 + 高频考点复盘"
        elif remaining <= 7:
            focus = "专题强化+模拟"
            task = f"{topic} 变式练习 + 综合题"
        else:
            focus = "基础巩固"
            task = f"{topic} 概念梳理 + 基础题"

        if error_count.get(topic, 0) >= 2 and "错题重做" not in task:
            task += "（含错题专项）"

        minutes = int(daily_hours * 60)
        if ability == "薄弱":
            minutes = int(minutes * 0.8)
        elif ability == "较好":
            minutes = int(minutes * 1.2)

        plan.append({
            "day": index,
            "date": (datetime.today() + timedelta(days=index-1)).strftime("%m/%d"),
            "task": task,
            "focus": focus,
            "minutes": minutes,
            "priority": "高" if topic in weak_topics[:2] else "中",
            "completed": False
        })
    return plan

def calculate_weak_index(weak_topics, wrong_questions):
    scores = []
    for idx, topic in enumerate(weak_topics, 1):
        related = sum(1 for w in wrong_questions if topic in w.get("knowledge_point", ""))
        recent = 0
        for w in wrong_questions:
            if topic in w.get("knowledge_point", ""):
                created = datetime.strptime(w.get("created_at", datetime.today().strftime("%m/%d %H:%M")), "%m/%d %H:%M")
                if (datetime.today() - created).days <= 7:
                    recent += 1
        score = min(10, 5 + related * 2 + recent * 1.5)
        scores.append({"topic": topic, "index": round(score, 1), "wrong_count": related})
    return scores

def analyze_wrong_question(question, error_type, knowledge_point):
    try:
        client = get_openai_client()
        if client:
            system_prompt = "你是智学伙伴，分析错题原因并给出复习建议。只输出JSON。"
            user_prompt = f"""
错题：{question}
错误类型：{error_type}
知识点：{knowledge_point}
请输出JSON：{{"knowledge_point":"更准确名称","error_type":"...","analysis":"...","next_action":"...","similar_questions":["题1","题2"]}}
"""
            resp = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}],
                temperature=0.3
            )
            data = extract_json_object(resp.choices[0].message.content)
            similar = data.get("similar_questions", [])
            if not similar:
                similar = [q[1] for q in find_similar_questions(knowledge_point)]
            return {
                "question": question,
                "error_type": data.get("error_type", error_type),
                "knowledge_point": data.get("knowledge_point", knowledge_point),
                "analysis": data.get("analysis", ""),
                "next_action": data.get("next_action", ""),
                "review_days": [1, 3, 7],
                "similar_questions": similar[:3],
                "created_at": datetime.today().strftime("%m/%d %H:%M"),
                "source": f"大模型 {OPENAI_MODEL}"
            }
    except Exception as e:
        pass

    hint = ERROR_HINTS.get(error_type, ERROR_HINTS["概念不清"])
    similar = [q[1] for q in find_similar_questions(knowledge_point)]
    return {
        "question": question,
        "error_type": error_type,
        "knowledge_point": knowledge_point,
        "analysis": f"该题属于“{knowledge_point}”。{hint}",
        "next_action": f"今晚复盘“{knowledge_point}”定义，并完成2道相似题。",
        "review_days": [1, 3, 7],
        "similar_questions": similar[:3],
        "created_at": datetime.today().strftime("%m/%d %H:%M"),
        "source": "本地规则"
    }

def build_summary(plan, wrong_questions, profile):
    total = len(plan)
    completed = sum(1 for item in plan if item.get("completed"))
    weak_points = sorted({w.get("knowledge_point", "") for w in wrong_questions})
    now = datetime.now()
    week_ago = now - timedelta(days=7)
    recent_wrong = [w for w in wrong_questions if datetime.strptime(w["created_at"], "%m/%d %H:%M") >= week_ago]
    old_wrong = [w for w in wrong_questions if datetime.strptime(w["created_at"], "%m/%d %H:%M") < week_ago]
    trend = "↓" if len(recent_wrong) < len(old_wrong) else "↑" if len(recent_wrong) > len(old_wrong) else "→"
    start_date = datetime.strptime(plan[0]["date"], "%m/%d") if plan else now
    study_days = (now - start_date.replace(year=now.year)).days + 1
    return {
        "plan_days": total,
        "wrong_count": len(wrong_questions),
        "completion_rate": round(completed / total * 100, 1) if total else 0,
        "completed": completed,
        "pending": total - completed,
        "weak_points": "、".join(weak_points) if weak_points else "暂无",
        "trend": trend,
        "study_days": study_days
    }

def build_review_schedule(wrong_questions):
    schedule = []
    for w in wrong_questions:
        for days in w["review_days"]:
            due = (datetime.today() + timedelta(days=days)).strftime("%m/%d")
            schedule.append({
                "knowledge_point": w["knowledge_point"],
                "question": w["question"][:20] + "..." if len(w["question"])>20 else w["question"],
                "due": due,
                "days": days
            })
    return sorted(schedule, key=lambda x: x["days"])

def get_active_reminder(plan, wrong_questions):
    pending = [item for item in plan if not item.get("completed")]
    if pending:
        next_task = pending[0]
        return f"⏰ 今日优先：Day{next_task['day']} {next_task['task']}（{next_task['minutes']}分钟）"
    if wrong_questions:
        return "📚 今日计划已完成！建议打开错题库进行复盘。"
    return "📝 请先生成学习计划。"

# ---------------------------- 路由 ----------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("username") == DEMO_USERNAME and request.form.get("password") == DEMO_PASSWORD:
            session["logged_in"] = True
            session["login_name"] = request.form.get("username")
            return redirect(url_for("index"))
        error = "账号或密码错误"
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
            "name": request.form.get("name", DEFAULT_PROFILE["name"]),
            "subject": request.form.get("subject", DEFAULT_PROFILE["subject"]),
            "exam_date": request.form.get("exam_date", DEFAULT_PROFILE["exam_date"]),
            "daily_hours": request.form.get("daily_hours", DEFAULT_PROFILE["daily_hours"]),
            "weak_topics": request.form.get("weak_topics", DEFAULT_PROFILE["weak_topics"]),
            "ability": request.form.get("ability", "一般")
        }
        session["profile"] = profile
        session["plan"] = generate_study_plan(profile, 0, [])
        session["wrong_questions"] = []
        session["activities"] = []
        return redirect(url_for("index"))

    profile = session.get("profile")
    plan = session.get("plan", [])
    wrong_questions = session.get("wrong_questions", [])
    activities = session.get("activities", [])
    weak_topics = split_topics(profile["weak_topics"]) if profile else []

    # 动态调整计划
    if plan and profile:
        completed = sum(1 for item in plan if item.get("completed"))
        if len(plan) > 0 and completed / len(plan) >= 0.8 and len(plan) - completed >= 3:
            adjusted_profile = profile.copy()
            adjusted_profile["ability"] = "较好"
            new_plan = generate_study_plan(adjusted_profile, completed, wrong_questions)
            for old_item in plan:
                if old_item.get("completed"):
                    for new_item in new_plan:
                        if new_item["day"] == old_item["day"]:
                            new_item["completed"] = True
                            break
            session["plan"] = new_plan
            plan = new_plan
            activities.append({"time": datetime.now().strftime("%H:%M"), "msg": "计划自动调整（完成率高，增强难度）"})
            session["activities"] = activities

    return render_template(
        "index.html",
        defaults=DEFAULT_PROFILE,
        profile=profile,
        plan=plan,
        wrong_questions=wrong_questions,
        summary=build_summary(plan, wrong_questions, profile),
        active_reminder=get_active_reminder(plan, wrong_questions),
        weak_topic_scores=calculate_weak_index(weak_topics, wrong_questions),
        review_schedule=build_review_schedule(wrong_questions),
        error_types=list(ERROR_HINTS.keys()),
        llm_enabled=get_openai_client() is not None,
        openai_model=OPENAI_MODEL,
        openai_base_url=OPENAI_BASE_URL,
        activities=activities,
        login_name=session.get("login_name")
    )

@app.route("/toggle/<int:day>", methods=["POST"])
@login_required
def toggle_task(day):
    plan = session.get("plan", [])
    for item in plan:
        if item["day"] == day:
            item["completed"] = not item.get("completed", False)
            activities = session.get("activities", [])
            status = "完成" if item["completed"] else "取消完成"
            activities.append({"time": datetime.now().strftime("%H:%M"), "msg": f"Day{day} {status}: {item['task'][:20]}"})
            session["activities"] = activities
            break
    session["plan"] = plan
    return redirect(url_for("index"))

@app.route("/wrong", methods=["POST"])
@login_required
def wrong():
    question = request.form.get("question", "").strip()
    error_type = request.form.get("error_type", "概念不清")
    knowledge_point = request.form.get("knowledge_point", "").strip()
    if not question or not knowledge_point:
        return redirect(url_for("index"))
    result = analyze_wrong_question(question, error_type, knowledge_point)
    wrong_questions = session.get("wrong_questions", [])
    wrong_questions.append(result)
    session["wrong_questions"] = wrong_questions
    activities = session.get("activities", [])
    activities.append({"time": datetime.now().strftime("%H:%M"), "msg": f"录入错题: {knowledge_point}"})
    session["activities"] = activities
    return redirect(url_for("index"))

@app.route("/wrong/<int:index>/delete", methods=["POST"])
@login_required
def delete_wrong(index):
    wrong_questions = session.get("wrong_questions", [])
    if 0 <= index < len(wrong_questions):
        deleted = wrong_questions.pop(index)
        session["wrong_questions"] = wrong_questions
        activities = session.get("activities", [])
        activities.append({"time": datetime.now().strftime("%H:%M"), "msg": f"删除错题: {deleted.get('knowledge_point','')}"})
        session["activities"] = activities
    return redirect(url_for("index"))

@app.route("/reset", methods=["GET"])
@login_required
def reset():
    session.pop("profile", None)
    session.pop("plan", None)
    session.pop("wrong_questions", None)
    session.pop("activities", None)
    return redirect(url_for("index"))

# ---------------------------- OCR 上传 ----------------------------
@app.route("/ocr_upload", methods=["POST"])
@login_required
def ocr_upload():
    if 'file' not in request.files:
        return jsonify({"error": "未上传文件"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "空文件名"}), 400

    recognized_text = ""
    if OCR_AVAILABLE and ocr_reader:
        try:
            from PIL import Image
            import numpy as np
            img_bytes = file.read()
            image = Image.open(BytesIO(img_bytes))
            img_np = np.array(image)
            result = ocr_reader.readtext(img_np, detail=0)
            recognized_text = "\n".join(result)
        except Exception as e:
            recognized_text = f"OCR识别失败: {str(e)}"
    else:
        recognized_text = f"【模拟OCR】识别到图片：{file.filename}，请手动输入题目内容。"
    return jsonify({"text": recognized_text})

# ---------------------------- 测验生成 ----------------------------
@app.route("/test/<int:index>", methods=["GET"])
@login_required
def generate_test(index):
    wrong_questions = session.get("wrong_questions", [])
    if 0 <= index < len(wrong_questions):
        item = wrong_questions[index]
        kp = item.get("knowledge_point", "")
        similar = find_similar_questions(kp)
        if similar:
            test_question = random.choice(similar)[1]
            return jsonify({"test": test_question, "knowledge_point": kp})
    return jsonify({"test": "暂无可用测验题", "knowledge_point": ""})

# ---------------------------- 启动 ----------------------------
if __name__ == "__main__":
    app.run(debug=True, port=5000)