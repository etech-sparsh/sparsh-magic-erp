"""Student-domain tools (learner self-service).

Catalog (Phase 1+): get_my_profile, get_my_batches, get_my_courses,
get_course_progress, get_my_sessions, get_upcoming_sessions, get_session_details,
get_my_attendance, get_attendance_summary, get_latest_quiz_result,
get_my_assessment_results, get_subject_wise_scores, analyze_student_performance,
get_learning_progress, get_pending_assignments, recommend_study_plan,
get_my_notifications.

Phase 1: get_my_profile, get_my_sessions, get_latest_quiz_result.
Phase 3: analyze_student_performance, get_subject_wise_scores,
         get_learning_progress, recommend_study_plan.
Importing the submodules here runs their @tool decorators so they self-register.
"""

from app.assistant.tools.student import (  # noqa: E402,F401
    assessment_tools,
    attendance_tools,
    content_tools,
    curriculum_tools,
    performance_tools,
    profile_tools,
    progress_tools,
    recommendation_tools,
    session_tools,
    support_engine_tools,
    task_tools,
)
