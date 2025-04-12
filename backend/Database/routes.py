from flask import request, Blueprint
from flask_jwt_extended import jwt_required, get_jwt_identity
from Database.db_utils import get_db,insert_questions
from bson import ObjectId
import traceback


db_bp = Blueprint("db_bp", __name__, url_prefix="/db")


@db_bp.post("/new_exam")
@jwt_required()
def new_exam():
    data = request.get_json()
    exam_name = data.get("exam_name")
    id = ObjectId(get_jwt_identity())
    
    db = get_db()
    teacher = db.Users.find_one({"_id": id})
    print(id)
    cursor = db.Exams.insert_one(
        {
            "exam_name": exam_name,
            "teacher_id": id,
            "teacher_name": teacher["username"],
        }
    )
    return {"message": "Exam created successfully", "exam_id": str(cursor.inserted_id)}

@db_bp.post("/submit_questions")
@jwt_required()
def new_question():
    try:
        data = request.get_json()
        questions = data.get("questions")
        exam_id = data.get("exam_id")
        arr = []
        for question in questions:
            arr.append({
                "question" : question,
                "exam_id" : exam_id
            })
        response = insert_questions(arr)
        if response["message"].startswith() == "Error:":
            return {
                "message" : response["message"]
            },400
        else:
            return {
                "message" : response["message"]
            },200
    except Exception:
        return {
            "message": "Error: "+traceback.format_exc()
        },500
        