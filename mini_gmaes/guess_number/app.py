from flask import Flask, render_template, request, jsonify
import random

app = Flask(__name__)

# 遊戲資料
students = []
answer = None
current_student = ""
history = []
winner = ""


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/start", methods=["POST"])
def start():
    global students, answer, current_student, history, winner

    # 使用換行切割學生名單
    text = request.form.get("students", "")
    names = text.split("\n")

    students = []

    for name in names:
        name = name.strip()

        if name != "":
            students.append(name)

    if len(students) == 0:
        return jsonify(error="請輸入學生名單"), 400

    try:
        answer = int(request.form.get("answer", ""))
    except ValueError:
        return jsonify(error="答案必須是整數"), 400

    current_student = ""
    history = []
    winner = ""

    return jsonify(students=students)


@app.route("/spin", methods=["POST"])
def spin():
    global current_student

    if answer is None:
        return jsonify(error="請先設定遊戲"), 400

    if winner != "":
        return jsonify(error="遊戲已結束"), 400

    # 隨機抽出一位學生
    index = random.randrange(len(students))
    current_student = students[index]

    return jsonify(
        name=current_student,
        index=index
    )


@app.route("/guess", methods=["POST"])
def guess():
    global winner, history

    if current_student == "":
        return jsonify(error="請先抽出學生"), 400

    if winner != "":
        return jsonify(error="遊戲已結束"), 400

    try:
        number = int(request.form.get("guess", ""))
    except ValueError:
        return jsonify(error="請輸入整數"), 400

    # 猜數字的判斷
    if number < answer:
        message = "再大"
    elif number > answer:
        message = "再小"
    else:
        message = "猜中了！"
        winner = current_student

    history.append({
        "name": current_student,
        "guess": number,
        "message": message
    })

    return jsonify(
        message=message,
        winner=winner,
        name=current_student,
        history=history
    )


if __name__ == "__main__":
    app.run(debug=True)