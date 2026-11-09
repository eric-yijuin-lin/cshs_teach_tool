"""課程學生名單批次輸出工具。

安裝：uv add openpyxl
執行：uv run python excel_course_tool_v3.py

輸入：src/*.xlsx，排除 src/template.xlsx。
每個來源工作表各重新讀取 template.xlsx，保留格式，輸出至
output/<年級>/<來源檔名移除「課程學生名單」>/<科目名稱>.xlsx。

安全檢查：不寫入 A4:A末列；學生班級缺漏不靜默帶過；
範本佔位文字缺失或格式不可安全保留時，不儲存該工作表。
"""

from __future__ import annotations

from copy import copy
from pathlib import Path
import re
import traceback
from typing import Any

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.cell.rich_text import CellRichText, TextBlock

SRC_DIR = Path("./class_schedule/src")
OUTPUT_DIR = Path("./class_schedule/output")
SOURCE_START_ROW = 9
TARGET_START_ROW = 4

STUDENT_FIELDS = {
    "cls": {"source_col": "C", "tokens": ("{st_cls}",)},
    "no": {"source_col": "E", "tokens": ("{st_no}",)},
    "name": {"source_col": "G", "tokens": ("{st_name}",)},
}
HEADER_FIELDS = {
    "A1": ("{class_type}",),
    "A2": ("{subject}",),
    "E2": ("{teacher}",),
    "I2": ("{cls_tm}",),
}
GRADE_NAMES = ("高一", "高二", "高三")
TYPE_NAMES = {"彈性": "彈性學習", "多元": "多元跑班", "藝能": "藝能跑班"}
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def text_of(value: Any) -> str:
    return "" if value is None else str(value).strip()


def remove_label(value: Any, label: str) -> str:
    return re.sub(rf"^{re.escape(label)}\s*[：:]?\s*", "", text_of(value)).strip()


def class_type_from_filename(stem: str) -> tuple[str, str]:
    grades = [grade for grade in GRADE_NAMES if grade in stem]
    types = [name for keyword, name in TYPE_NAMES.items() if keyword in stem]
    if len(grades) != 1 or len(types) != 1:
        raise ValueError(f"檔名無法唯一判定年級／課程類型：{stem} (年級={grades}, 類型={types})")
    return grades[0], grades[0] + types[0]


def safe_name(name: str) -> str:
    result = INVALID_FILENAME_CHARS.sub("_", name).strip().rstrip(" .")
    if not result:
        raise ValueError("輸出檔案或資料夾名稱為空")
    return result


def parse_class_time(value: Any) -> str:
    raw = remove_label(value, "上課時間")
    parts = raw.split("．")
    if len(parts) != 2:
        raise ValueError(f"H6 上課時間格式不符：{value!r}，應如『上課時間：三．567』")
    weekday, periods = (v.strip() for v in parts)
    if not weekday or not periods.isdigit():
        raise ValueError(f"H6 星期或節次格式錯誤：{value!r}")
    return (weekday if weekday.startswith("週") else "週" + weekday) + ".".join(periods)


def find_token(value: Any, tokens: tuple[str, ...], coordinate: str) -> str:
    matches = [token for token in tokens if token in str(value or "")]
    if len(matches) != 1:
        raise ValueError(f"範本 {coordinate} 需要恰好一個佔位文字 {tokens}，實際內容：{value!s}")
    return matches[0]


def replace_text_preserving_runs(cell, token: str, new_value: Any) -> None:
    """替換 token，保留既有儲存格樣式與富文字片段樣式。

    如果 token 橫跨不同 Rich Text run，以 token 首字元的樣式作為新文字的樣式。
    不會自行套用紅字；只沿用範本中的格式。
    """
    if isinstance(cell, MergedCell):
        raise ValueError(f"目標 {cell.coordinate} 是合併儲存格的非左上角")
    value = cell.value
    if value is None or token not in str(value):
        raise ValueError(f"目標 {cell.coordinate} 找不到佔位文字 {token}")
    replacement = text_of(new_value)
    if not isinstance(value, CellRichText):
        cell.value = str(value).replace(token, replacement)
        return

    # 保留各個 Rich Text 字元的字型資訊；避免把紅色 token 變成普通黑字。
    chars: list[tuple[str, Any]] = []
    for part in value:
        part_text = part.text if isinstance(part, TextBlock) else str(part)
        font = copy(part.font) if isinstance(part, TextBlock) else None
        chars.extend((char, font) for char in part_text)
    original = "".join(char for char, _ in chars)
    positions = [m.start() for m in re.finditer(re.escape(token), original)]
    if not positions:
        raise ValueError(f"富文字 {cell.coordinate} 找不到完整佔位文字 {token}")

    output: list[tuple[str, Any]] = []
    cursor = 0
    for start in positions:
        output.extend(chars[cursor:start])
        style = chars[start][1]
        output.extend((char, copy(style)) for char in replacement)
        cursor = start + len(token)
    output.extend(chars[cursor:])

    runs = CellRichText()
    buffer = ""
    last_font = None
    for char, font in output:
        if buffer and font != last_font:
            runs.append(TextBlock(copy(last_font), buffer) if last_font is not None else buffer)
            buffer = ""
        buffer += char
        last_font = font
    if buffer:
        runs.append(TextBlock(copy(last_font), buffer) if last_font is not None else buffer)
    cell.value = runs

    # 讀回字串檢查；若格式保留失敗，後續不存檔。
    expected = original.replace(token, replacement)
    if str(cell.value) != expected:
        raise AssertionError(f"{cell.coordinate} 富文字替換內容驗證失敗")


def get_student_positions(ws) -> dict[str, tuple[int, str]]:
    positions: dict[str, tuple[int, str]] = {}
    for cell in ws[TARGET_START_ROW]:
        for field, specification in STUDENT_FIELDS.items():
            matches = [t for t in specification["tokens"] if t in str(cell.value or "")]
            if not matches:
                continue
            if field in positions or len(matches) != 1:
                raise ValueError(f"範本第 {TARGET_START_ROW} 列存在重複學生欄位：{field}")
            if cell.column == 1:
                raise ValueError(f"範本 {cell.coordinate} 位於 A 欄（編號欄），禁止寫入")
            positions[field] = (cell.column, matches[0])
    missing = set(STUDENT_FIELDS) - set(positions)
    if missing:
        raise ValueError(f"範本第 {TARGET_START_ROW} 列找不到：{sorted(missing)}；實際為：" +
                         repr([(c.coordinate, str(c.value)) for c in ws[TARGET_START_ROW] if c.value is not None]))
    if len({col for col, _ in positions.values()}) != len(positions):
        raise ValueError("學生不同欄位指向同一格，停止以避免誤寫")
    return positions


def read_students(ws) -> list[dict[str, Any]]:
    # 來源 D 欄若為垂直合併區域，取合併區左上角的班級資訊。
    inherited_class: dict[int, Any] = {}
    for merged in ws.merged_cells.ranges:
        if merged.min_col <= 4 <= merged.max_col and merged.max_row >= SOURCE_START_ROW:
            first = ws.cell(merged.min_row, merged.min_col).value
            for row in range(max(SOURCE_START_ROW, merged.min_row), merged.max_row + 1):
                inherited_class[row] = first

    students = []
    for row in range(SOURCE_START_ROW, ws.max_row + 1):
        cls = ws[f"D{row}"].value
        no = ws[f"E{row}"].value
        name = ws[f"G{row}"].value
        if not text_of(cls):
            cls = inherited_class.get(row)
        if not any(text_of(v) for v in (cls, no, name)):
            continue
        # 若 D/E/G 不是學生資料完整欄位，不要靜默寫成空白。
        if not text_of(cls):
            raise ValueError(f"來源 {ws.title}!D{row} 班級為空（E{row}={no!r}, G{row}={name!r}）；請檢查來源 D 欄")
        if not text_of(name):
            raise ValueError(f"來源 {ws.title}!G{row} 姓名為空；可能已讀到學生名單以外的內容")
        students.append({"cls": cls, "no": no, "name": name, "source_row": row})
    if not students:
        raise ValueError(f"來源工作表 {ws.title} 自第 {SOURCE_START_ROW} 列起沒有可用學生")
    return students


def fill_students(source_ws, target_ws) -> int:
    positions = get_student_positions(target_ws)
    students = read_students(source_ws)
    final_row = TARGET_START_ROW + len(students) - 1
    if final_row > target_ws.max_row:
        raise ValueError(f"範本只有 {target_ws.max_row} 列，需要至少 {final_row} 列，不插入列以免破壞編號")

    # 全面預檢，避免寫入非學生欄位的既有內容。
    for offset in range(len(students)):
        for field, (column, token) in positions.items():
            cell = target_ws.cell(TARGET_START_ROW + offset, column)
            if isinstance(cell, MergedCell):
                raise ValueError(f"目標 {cell.coordinate} 是合併儲存格，不可寫入")
            current = text_of(cell.value)
            if current and token not in current:
                raise ValueError(f"目標 {cell.coordinate} 含有不可覆蓋的內容：{current!r}")

    for offset, student in enumerate(students):
        for field, (column, token) in positions.items():
            cell = target_ws.cell(TARGET_START_ROW + offset, column)
            value = student[field]
            if cell.value is not None and token in str(cell.value):
                replace_text_preserving_runs(cell, token, value)
            else:
                cell.value = value  # 僅修改既有空白學生欄；保留原 Cell 樣式
    # 验证實際班級值，不接受空白寫入而仍視為完成。
    for offset, student in enumerate(students):
        cls_col, _ = positions["cls"]
        saved_cls = target_ws.cell(TARGET_START_ROW + offset, cls_col).value
        if text_of(saved_cls) != text_of(student["cls"]):
            raise AssertionError(f"班級寫入驗證失敗：第 {TARGET_START_ROW+offset} 列，預期={student['cls']!r}，實際={saved_cls!r}")
    return len(students)


def capture_number_column(ws) -> list[tuple[int, Any, Any]]:
    """保存 A4:A末列各格的值及樣式；只做原樣比較，不覆蓋。"""
    return [(row, copy(ws.cell(row, 1).value), copy(ws.cell(row, 1)._style))
            for row in range(TARGET_START_ROW, ws.max_row + 1)]


def verify_number_column(ws, snapshot) -> None:
    current = capture_number_column(ws)
    if len(snapshot) != len(current):
        raise AssertionError("Template A 欄列數改變，停止存檔")
    for before, after in zip(snapshot, current):
        if before != after:
            raise AssertionError(f"Template A{before[0]} 原始編號或格式遭到變更，停止存檔：原本={before[1]!r}，目前={after[1]!r}")

def clear_unused_placeholders(template_ws, start_row=4):
    placeholders = ("{st_cls}", "{st_no}", "{st_name}")

    cleared_count = 0

    # 從第 4 列開始，略過 A 欄（編號）
    for row in template_ws.iter_rows(
        min_row=start_row,
        min_col=2,
        max_row=template_ws.max_row,
        max_col=template_ws.max_column
    ):
        for cell in row:
            if not isinstance(cell.value, str):
                continue

            original = cell.value
            updated = original

            for placeholder in placeholders:
                updated = updated.replace(placeholder, "")

            if updated != original:
                cell.value = updated
                cleared_count += 1

    return cleared_count


def run(src_dir: Path = SRC_DIR, output_dir: Path = OUTPUT_DIR) -> None:
    template_path = src_dir / "template.xlsx"
    if not template_path.is_file():
        raise FileNotFoundError(f"缺少範本：{template_path}")
    ok = 0
    failed = 0
    for file_path in sorted(src_dir.glob("*.xlsx")):
        if file_path.name.lower() == "template.xlsx" or file_path.name.startswith("~$"):
            continue
        try:
            grade, class_type = class_type_from_filename(file_path.stem)
            folder_name = safe_name(file_path.stem.replace("各課程學生名單", ""))
            source_wb = load_workbook(file_path, data_only=True)
        except Exception:
            failed += 1
            print(f"\n[來源檔失敗] {file_path.name}")
            traceback.print_exc()
            continue

        try:
            for source_ws in source_wb.worksheets:
                target_wb = None
                try:
                    subject = remove_label(source_ws["A4"].value, "科目名稱")
                    teacher = remove_label(source_ws["A5"].value, "授課教師") or "待補"
                    class_time = parse_class_time(source_ws["H6"].value)
                    if not subject:
                        raise ValueError(f"來源 {source_ws.title}!A4 科目名稱為空")

                    # 每個 Sheet 都重新讀取乾淨的範本。
                    target_wb = load_workbook(template_path, rich_text=True)
                    target_ws = target_wb.active
                    a_snapshot = capture_number_column(target_ws)

                    headers = {"A1": class_type, "A2": subject, "E2": teacher, "I2": class_time}
                    for address, value in headers.items():
                        token = find_token(target_ws[address].value, HEADER_FIELDS[address], address)
                        replace_text_preserving_runs(target_ws[address], token, value)

                    count = fill_students(source_ws, target_ws)
                    clear_unused_placeholders(target_ws)
                    verify_number_column(target_ws, a_snapshot)

                    output_file = output_dir / grade / folder_name / (safe_name(subject) + ".xlsx")
                    output_file.parent.mkdir(parents=True, exist_ok=True)
                    target_wb.save(output_file)  # 同名覆蓋
                    ok += 1

                    print(f"[完成] {file_path.name} / {source_ws.title}：{count} 人 → {output_file}")
                except Exception:
                    failed += 1
                    print(f"\n[失敗] {file_path.name} / {source_ws.title}")
                    traceback.print_exc()
                finally:
                    if target_wb is not None:
                        target_wb.close()
        finally:
            source_wb.close()
    print(f"\n處理完成：成功 {ok} 份，失敗 {failed} 份")


if __name__ == "__main__":
    run()
