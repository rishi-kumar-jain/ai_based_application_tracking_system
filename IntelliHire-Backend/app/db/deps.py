from fastapi import Request

def get_db(request: Request):
    session_maker = request.app.state.session_maker
    db = session_maker()
    try:
        yield db
    finally:
        db.close()
