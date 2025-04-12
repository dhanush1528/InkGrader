from flask import Flask, request, jsonify
from dotenv import load_dotenv
import os
from datetime import timedelta
from flask_jwt_extended import (
    JWTManager,
    jwt_required,
    get_jwt,
    create_access_token,
    create_refresh_token,
    get_jwt_identity,
)
from flask_cors import CORS
from bson import ObjectId
from OCRSpace import API, Engine
from Database.db_utils import (
    get_db,
    insert_questions,
    create_student_user,
    create_teacher_user,
    authenticate_user,
)
from Agent import ExtractionAgent, EvaluationAgent
from PyPDF2 import PdfReader
import traceback
import re
import base64
from werkzeug.utils import secure_filename

# Initialize Flask app
app = Flask(__name__)
jwt = JWTManager(app)
BLOCKLIST = set()
CORS(app, resources={r"/*": {"origins": "*"}})

UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# Home route
@app.route("/", methods=["GET", "POST"])
def home():
    return {"message": "InkGrader Backend API"}


# JWT token blocklist loader
@jwt.token_in_blocklist_loader
def check_if_token_revoked(jwt_header, jwt_payload):
    jti = jwt_payload["jti"]
    return jti in BLOCKLIST


# Auth routes
@app.route("/auth/register", methods=["POST"])
def register():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")
    email = data.get("email")
    teacher_id = data.get("teacher_id")
    student_id = data.get("student_id")
    response = None
    if teacher_id:
        response = create_teacher_user(username, password, email, teacher_id)
    if student_id:
        response = create_student_user(username, password, email, student_id)
    if response["message"].startswith("DuplicateKeyError") or response[
        "message"
    ].startswith("OperationFailure"):
        return response, 409

    access_token = create_access_token(identity=response["id"], fresh=True)
    refresh_token = create_refresh_token(identity=response["id"])
    return {
        "message": response["message"],
        "access_token": access_token,
        "refresh_token": refresh_token,
    }


@app.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")
    response = authenticate_user(email, password)
    if response.get("message") == "User authenticated successfully.":
        access_token = create_access_token(identity=response["id"], fresh=True)
        refresh_token = create_refresh_token(identity=response["id"])
        return {
            "message": "Logged in successfully",
            "access_token": access_token,
            "refresh_token": refresh_token,
        }, 200
    else:
        return {"message": "Invalid credentials"}, 401


@app.route("/auth/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    email = get_jwt_identity()
    access_token = create_access_token(identity=email, fresh=False)
    return {"access_token": access_token}, 200


@app.route("/auth/logout", methods=["POST"])
@jwt_required(refresh=True)
def logout():
    jti = get_jwt()["jti"]
    if jti:
        BLOCKLIST.add(jti)
        return {"message": "Logged out successfully"}, 200
    else:
        return {"message": "No active token found"}, 401


# OCR routes
@app.route("/ocr/demo", methods=["POST"])
def ocr_demo():
    try:
        image = request.files.get("image")
        question = request.form.get("question")
        marks = request.form.get("marks")
        db = get_db()

        if image and question and marks:
            filename = secure_filename(image.filename)
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            image.save(file_path)

            # OCR + preprocessing
            api = API(api_key=os.getenv("OCR_API_KEY"), engine=Engine.ENGINE_2)
            text = api.ocr_file(file_path)
            processed_text = (
                re.sub(r"\s+", " ", text).strip().lower() + " marks: " + str(marks)
            )
            os.remove(file_path)

            # Grade the answer
            grader = EvaluationAgent()
            grader.set_rubric_and_answers(question, processed_text)
            grading_result = grader.grade()

            # Convert eval keys to strings for MongoDB
            safe_grading_result = {
                "total_marks": grading_result["total_marks"],
                "evaluations": {
                    str(k): v for k, v in grading_result["evaluations"].items()
                },
            }

            # Store in DB
            db.test.insert_one(
                {
                    "question": question,
                    "student_answer": processed_text,
                    "grading_result": safe_grading_result,
                }
            )
            return {
                "message": "Graded and saved successfully",
                "grading_result": safe_grading_result,
                "extracted_text": processed_text,
            }, 200

        else:
            return {"message": "Wrong fields sent in request"}, 400

    except Exception:
        return {"message": "Error: " + traceback.format_exc()}, 500


@app.route("/ocr/bulk", methods=["POST"])
def ocr_bulk():
    # Placeholder for bulk OCR logic
    return {"message": "Bulk OCR not implemented yet"}, 501


# Database routes
@app.route("/db/exam", methods=["POST", "GET"])
@jwt_required()
def exam():
    try:
        db = get_db()
        user_id = ObjectId(get_jwt_identity())
        if request.method == "POST":
            data = request.get_json()
            exam_name = data.get("exam_name")
            teacher = db.Users.find_one({"_id": user_id})
            if not teacher:
                return jsonify({"message": "Teacher not found"}), 404

            result = db.Exams.insert_one(
                {
                    "exam_name": exam_name,
                    "teacher_id": user_id,
                    "teacher_name": teacher.get("username"),
                }
            )
            return (
                jsonify(
                    {
                        "message": "Exam created successfully",
                        "exam_id": str(result.inserted_id),
                    }
                ),
                201,
            )

        elif request.method == "GET":
            exams = db.Exams.find({"teacher_id": user_id})
            exam_list = [
                {
                    "exam_id": str(exam["_id"]),
                    "exam_name": exam.get("exam_name"),
                    "teacher_name": exam.get("teacher_name"),
                }
                for exam in exams
            ]
            return jsonify({"exams": exam_list}), 200

    except Exception:
        return jsonify({"message": "Error: " + traceback.format_exc()}), 500


@app.route("/db/questions", methods=["POST", "GET"])
@jwt_required()
def questions():
    try:
        db = get_db()
        if request.method == "POST":
            data = request.get_json()
            exam_id = data.get("exam_id")
            rubric = data.get("rubric")
            student_answers = data.get("student_answers")

            if not all([exam_id, rubric, student_answers]):
                return jsonify({"message": "Missing required fields"}), 400

            extractor = ExtractionAgent()
            extracted_data = extractor.extract(rubric)

            db.ExtractedData.insert_one(
                {"exam_id": ObjectId(exam_id), "extracted_data": extracted_data}
            )
            return (
                jsonify(
                    {
                        "message": "Data extracted successfully",
                        "extracted_data": extracted_data,
                    }
                ),
                200,
            )

        elif request.method == "GET":
            exam_id = request.args.get("exam_id")
            if not exam_id:
                return jsonify({"message": "Missing exam_id parameter"}), 400

            exam = db.Exams.find_one({"_id": ObjectId(exam_id)})
            if not exam:
                return jsonify({"message": "Exam not found"}), 404

            pdf_path = exam.get("pdf_path")
            if not pdf_path:
                return jsonify({"message": "PDF path not found in exam document"}), 404

            with open(pdf_path, "rb") as pdf_file:
                reader = PdfReader(pdf_file)
                text = "".join([page.extract_text() for page in reader.pages])

            questions = []
            for line in text.split("\n"):
                if line.strip().startswith(("1.", "2.", "3.")):
                    questions.append({"text": line.strip(), "marks": 0})

            db.Questions.insert_many(
                [
                    {
                        "exam_id": ObjectId(exam_id),
                        "question": q["text"],
                        "marks": q["marks"],
                    }
                    for q in questions
                ]
            )
            return (
                jsonify(
                    {
                        "message": "Questions extracted and saved successfully",
                        "questions": questions,
                    }
                ),
                200,
            )

    except Exception:
        return jsonify({"message": "Error: " + traceback.format_exc()}), 500


# Error handler
@app.errorhandler(404)
def not_found(error):
    return {"message": "Not found"}, 404


# App configuration and run
if __name__ == "__main__":
    load_dotenv()
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(minutes=30)
    app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(minutes=120)
    app.config["JWT_SECRET_KEY"] = JWT_SECRET_KEY
    app.run()
