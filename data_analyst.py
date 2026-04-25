import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import os
from config import CHARTS_DIR, MODELS, get_logger
from smart_router import smart_call
from errors import Result

log = get_logger("data_analyst")
os.makedirs(CHARTS_DIR, exist_ok=True)

def load_file(filepath):
    try:
        ext = filepath.split('.')[-1].lower()
        if ext == 'csv':
            df = pd.read_csv(filepath)
        elif ext in ['xlsx', 'xls']:
            df = pd.read_excel(filepath)
        else:
            return None, f"Unsupported file type: {ext}"
        return df, None
    except Exception as e:
        return None, str(e)

def summarize_data(df):
    rows, cols = df.shape
    col_names = list(df.columns)
    numeric_cols = df.select_dtypes(include='number').columns.tolist()
    summary = []
    summary.append(f"Rows: {rows}, Columns: {cols}")
    summary.append(f"Columns: {', '.join(col_names)}")
    if numeric_cols:
        for col in numeric_cols[:5]:
            summary.append(f"{col} → min: {df[col].min():.2f}, max: {df[col].max():.2f}, avg: {df[col].mean():.2f}")
    return "\n".join(summary)

def generate_chart(df, chart_type='bar', x_col=None, y_col=None, title='Chart'):
    try:
        numeric_cols = df.select_dtypes(include='number').columns.tolist()
        if not numeric_cols:
            return None, "No numeric columns found for chart"
        y_col = y_col or numeric_cols[0]
        x_col = x_col or (df.columns[0] if df.columns[0] != y_col else df.index)
        plt.figure(figsize=(10, 5))
        if chart_type == 'bar':
            df.plot(kind='bar', x=x_col if x_col in df.columns else None, y=y_col, ax=plt.gca(), legend=False)
        elif chart_type == 'line':
            df.plot(kind='line', x=x_col if x_col in df.columns else None, y=y_col, ax=plt.gca(), legend=False)
        elif chart_type == 'pie':
            df[y_col].plot(kind='pie', ax=plt.gca(), autopct='%1.1f%%')
        elif chart_type == 'scatter':
            x_num = numeric_cols[0]
            y_num = numeric_cols[1] if len(numeric_cols) > 1 else numeric_cols[0]
            plt.scatter(df[x_num], df[y_num], alpha=0.6)
            plt.xlabel(x_num)
            plt.ylabel(y_num)
        elif chart_type == 'histogram':
            df[y_col].hist(bins=20, ax=plt.gca(), edgecolor='black')
            plt.xlabel(y_col)
            plt.ylabel('Frequency')
        elif chart_type == 'heatmap':
            corr = df[numeric_cols].corr()
            plt.imshow(corr, cmap='coolwarm', aspect='auto')
            plt.colorbar()
            plt.xticks(range(len(corr.columns)), corr.columns, rotation=45)
            plt.yticks(range(len(corr.columns)), corr.columns)
        elif chart_type == 'box':
            df[numeric_cols[:5]].plot(kind='box', ax=plt.gca())
        else:
            df.plot(kind='bar', y=y_col, ax=plt.gca(), legend=False)
        plt.title(title)
        plt.tight_layout()
        chart_path = f"{CHARTS_DIR}/{title.replace(' ', '_')}.png"
        plt.savefig(chart_path)
        plt.close()
        return chart_path, None
    except Exception as e:
        return None, str(e)


def smart_chart_suggestion(df) -> str:
    """Phase 5.4: Auto-suggest best chart type based on data shape."""
    numeric_cols = df.select_dtypes(include='number').columns.tolist()
    cat_cols = df.select_dtypes(include='object').columns.tolist()
    rows = len(df)

    if len(numeric_cols) >= 2 and rows > 20:
        return 'scatter'
    elif len(numeric_cols) >= 3:
        return 'heatmap'
    elif len(cat_cols) >= 1 and len(numeric_cols) >= 1 and rows <= 20:
        return 'bar'
    elif rows > 50 and len(numeric_cols) >= 1:
        return 'histogram'
    elif len(numeric_cols) == 1 and rows <= 10:
        return 'pie'
    else:
        return 'bar'

def ai_analyze(df, question="What are the key insights from this data?"):
    summary = summarize_data(df)
    sample = df.head(5).to_string()
    prompt = f"""You are a data analyst. Analyze this dataset and answer the question.

Dataset Summary:
{summary}

Sample Data (first 5 rows):
{sample}

Question: {question}

Give a clear, concise analysis in 3-5 sentences."""

    try:
        response = smart_call(prompt, intent="data_analysis")
        return response
    except Exception as e:
        log.error(f"Data analysis failed: {e}")
        return f"Analysis failed: {e}"

def analyze_file(filepath, question=None, chart_type='bar') -> Result:
    try:
        df, error = load_file(filepath)
        if error:
            return Result.failure(f"Error loading file: {error}", error_type="not_found")
        summary = summarize_data(df)
        analysis = ai_analyze(df, question or "What are the key insights from this data?")
        numeric_cols = df.select_dtypes(include='number').columns.tolist()
        chart_note = ""
        if numeric_cols:
            chart_path, err = generate_chart(df, chart_type=chart_type, title=os.path.basename(filepath))
            if chart_path:
                chart_note = f"\n📈 Chart saved: {chart_path}"
            else:
                log.warning(f"Chart generation failed: {err}")
        return Result.success(f"{analysis}{chart_note}")
    except Exception as e:
        return Result.from_exception(e)

if __name__ == "__main__":
    path = input("Enter file path (CSV or Excel): ").strip()
    analyze_file(path)
