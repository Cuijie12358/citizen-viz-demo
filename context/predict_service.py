"""
公民申请成功率预测 Flask 服务（方案 A）

启动:
    pip3 install flask flask-cors
    python3 context/predict_service.py
    # 访问 http://127.0.0.1:5050/predict.html

接口:
    POST /api/predict   body: {"text": "..."}
    返回: {"success": True/False, "probability": 0.86, "features": {...},
           "missing": [...], "analysis": {...}}

注：可视化页面默认使用浏览器内嵌模型推理（model.json），
    本服务为可选的服务端方案，便于后续扩展（日志/A-B/动态模型）。
"""
import json
import pickle
from pathlib import Path

import numpy as np
from flask import Flask, request, jsonify, send_from_directory

# 复用 scraper 的 regex 提取函数
import sys
sys.path.insert(0, str(Path(__file__).parent))
import scraper  # noqa: E402

ROOT = Path(__file__).parent
MODEL_PKL = ROOT / "model.pkl"

app = Flask(__name__, static_folder=str(ROOT))


def _load():
    with open(MODEL_PKL, 'rb') as f:
        return pickle.load(f)


BUNDLE = _load()


def extract_features(text: str) -> dict:
    """复用 scraper 中的 regex"""
    return {
        'age': scraper.p_age(text),
        'gender': scraper.p_gender(text),
        'marital': scraper.p_marital(text),
        'education': scraper.p_education(text),
        'monthly_income': scraper.p_income_monthly(text),
        'years_in_sg': scraper.p_years_in_sg(text),
        'pr_duration_years': scraper.p_pr_duration_years(text),
        'children': scraper.p_children(text),
        'has_property': scraper.p_property(text),
        'industry': scraper.p_industry(text),
    }


def vectorize(features: dict) -> np.ndarray:
    row = []
    for f in BUNDLE['num_features']:
        v = features.get(f)
        row.append(float(v) if v is not None else BUNDLE['num_medians'][f])
    for f in BUNDLE['cat_features']:
        rv = features.get(f)
        rv_str = str(rv) if rv is not None else None
        for v in BUNDLE['cat_vocab'][f]:
            row.append(1.0 if rv_str == v else 0.0)
    return np.array([row])


def check_missing(features: dict):
    """返回 (critical_missing, optional_missing)"""
    critical = ['age', 'education', 'pr_duration_years', 'years_in_sg']
    optional = ['gender', 'marital', 'monthly_income', 'children', 'has_property', 'industry']
    miss_c = [f for f in critical if features.get(f) is None]
    miss_o = [f for f in optional if features.get(f) is None]
    return miss_c, miss_o


@app.route('/api/predict', methods=['POST'])
def api_predict():
    payload = request.get_json(force=True) or {}
    text = (payload.get('text') or '').strip()
    if not text:
        return jsonify({'success': False, 'error': '请输入申请人信息文本'}), 400

    features = extract_features(text)
    miss_c, miss_o = check_missing(features)

    X = vectorize(features)
    proba = float(BUNDLE['model'].predict_proba(X)[0][1])

    return jsonify({
        'success': True,
        'probability': proba,
        'features': features,
        'missing_critical': miss_c,
        'missing_optional': miss_o,
        'feature_importance': dict(zip(
            BUNDLE['feature_names'],
            map(float, BUNDLE['model'].feature_importances_),
        )),
    })


@app.route('/predict.html')
@app.route('/citizen_viz.html')
@app.route('/<path:fname>')
def static_files(fname='citizen_viz.html'):
    return send_from_directory(str(ROOT), fname)


if __name__ == '__main__':
    print("=" * 55)
    print("  预测服务: http://127.0.0.1:5050/citizen_viz.html")
    print("=" * 55)
    app.run(host='127.0.0.1', port=5050, debug=False)
