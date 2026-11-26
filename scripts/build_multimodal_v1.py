"""Dựng eval/multimodal_v1.jsonl: 9 dòng draft đã duyệt (multimodal_v1_draft.jsonl) + 141 dòng mới.

Dữ liệu (URL bài, file đính kèm, sha256 ảnh) đã kiểm tra trong Postgres / Qdrant v3 (2026-11-07).
Phân bổ theo báo cáo đã duyệt (eval/research-multimodal-coverage.md mục 4):
T1 20 (neo golden_v2) | T2 25 | T3 15 | T4 15 | T5 15 | I1 20 | I2 12 | I3 10 | I4 8 | S 10.
Chủ dự án (2026-11-07): GIỮ mm-t2-01 nguyên trạng (khoét lỗi m001), KHÔNG thêm biến thể ảnh
chụp màn hình — 20 ảnh trong eval/images/ là bộ cuối.

Run: python3 scripts/build_multimodal_v1.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- URL thường dùng -------------------------------------------------------
TIN = "https://sict.haui.edu.vn/vn/tin-tuc/"
U_LE_TOT_NGHIIEP_2026 = TIN + "hon-1-000-tan-thac-si-ky-su-va-cu-nhan-sict-san-sang-buoc-vao-hanh-trinh-moi-lam-chu-cong-nghe-va-kien-tao-tuong-lai/71855"
U_KHAI_TRUONG_LAB = TIN + "khai-truong-phong-lab-haui-vtit-dau-moc-moi-trong-hop-tac-dao-tao-nguon-nhan-luc-cong-nghe-giua-dai-hoc-cong-nghiep-ha-noi-va-viettel-software/71835"
U_HOI_THAO_TOURNAMENT = TIN + "sict-tournament-2026-bung-no-nhiet-huyet-ket-noi-dam-me-lan-toa-tinh-than-tuoi-tre/71718"
U_NGAY_HOI_VL_2024 = TIN + "gan-1000-co-hoi-viec-lam-tai-ngay-hoi-viec-lam-cong-nghe-thong-tin-2024/71141"
U_IM_HAUIER = TIN + "i-m-hauier-loi-tri-an-cua-sinh-vien-cong-nghe-thong-tin-truong-dh-cong-nghiep-ha-noi/70764"
U_PROCON = TIN + "procon-haui-2026-cong-bo-ket-qua-vong-cap-dai-hoc-vinh-danh-nhung-doi-thi-xuat-sac/71951"
U_SPC = TIN + "software-product-challenge-2026-vinh-danh-cac-doi-thi-xuat-sac-tai-vong-chung-ket/71931"
U_SPC_DOUBLET = TIN + "spc-2026-vinh-danh-doi-doublet-voi-raghub-nen-tang-rag-chatbot-da-mien/71933"
U_PHU_NU = TIN + "sict-haui-rang-ro-va-am-ap-chuong-trinh-ky-niem-ngay-phu-nu-viet-nam-20-10/71939"
U_IT_SUPPORTER = TIN + "it-supporter-tan-tam-cham-soc-laptop-dong-hanh-cung-sinh-vien/71937"
U_IT_SUPPORTER_12 = TIN + "le-ky-niem-12-nam-thanh-lap-doi-ho-tro-ky-thuat-it-supporter-12-nam-khat-vong-vuon-xa/71890"
U_TET_AM = TIN + "tet-am-yeu-thuong-2026-hanh-trinh-se-chia-tu-trai-tim-tuoi-tre/71629"
U_XUAN_YEU_THUONG = TIN + "xuan-yeu-thuong-2026-lan-toa-hoi-am-yeu-thuong-toi-diem-truong-vung-cao-lai-chau/71630"
U_XUAN_DOAN_VIEN = TIN + "haui-to-chuc-chuong-trinh-xuan-doan-vien-tet-sum-vay-nam-2026/71604"
U_MOC_CHAU = TIN + "dang-bo-bo-phan-truong-cntt-tt-ve-nguon-tai-moc-chau-hanh-trinh-tri-an-lich-su-boi-dap-niem-tin-cach-mang/71609"
U_ICISN = TIN + "sinh-vien-sict-haui-tu-tin-toa-sang-tai-hoi-thao-quoc-te-icisn-2026/71670"
U_GUET = TIN + "hanh-trinh-hoc-tap-trao-doi-va-hop-tac-tai-guet-trung-quoc/71940"
U_JIS = TIN + "giao-luu-an-tuong-giua-sinh-vien-truong-dai-hoc-jis-an-do-va-sinh-vien-truong-sict-haui/71384"
U_CLUB_DAY_2023 = TIN + "ngay-hoi-cau-lac-bo-khoa-cong-nghe-thong-tin-2023/70734"
U_K21 = TIN + "welcome-to-sict-k21-programming-your-future/71893"
U_K21_DAU_TIEN = TIN + "chao-don-tan-sinh-vien-k21-sict-hanh-trinh-moi-bat-dau-tu-nhung-ngay-dau-tien/71886"
U_K21_INTL = TIN + "sict-chao-don-tan-sinh-vien-k21-cac-chuong-trinh-dao-tao-bang-tieng-anh/71892"
U_TAN_SV_1000 = TIN + "chao-don-gan-1000-tan-sinh-vien-khoa-cong-nghe-thong-tin-khoi-day-mo-uoc-gieo-mam-tuong-lai/70716"
U_SAMSUNG_STP = TIN + "sinh-vien-sict-haui-vinh-du-nhan-hoc-bong-tai-nang-samsung-stp-2025/71623"
U_NCKH_TRAO_GIAI = "https://sict.haui.edu.vn/vn/tin-khcn/61-cong-trinh-khoa-hoc-khoa-cntt-duoc-khen-thuong-tai-le-trao-giai-sinh-vien-nghien-cuu-khoa-hoc-nam-hoc-2023-2024/70955"
U_NHOM_NCUU = TIN + "cong-bo-cac-nhom-nghien-cuu-tai-dai-hoc-cong-nghiep-ha-noi-khang-dinh-chien-luoc-phat-trien-khoa-hoc-cong-nghe-va-vai-tro-tien-phong-cua-truong-cong-nghe-thong-tin-truyen-thong/71586"
U_TUYEN_SINH_PHU_THO = TIN + "sict-ket-noi-va-dinh-huong-nghe-nghiep-cho-hoc-sinh-phu-tho-tai-chuong-trinh-tu-van-tuyen-sinh-2026/71618"
U_TUYEN_SINH_HP = TIN + "soi-dong-ngay-hoi-tu-van-tuyen-sinh-huong-nghiep-2026-tai-hai-phong/71669"
U_TUYEN_SINH_LTT = TIN + "soi-dong-ngay-hoi-tu-van-huong-nghiep-nam-2026-tai-truong-thpt-ly-thai-to-bac-ninh/71665"
U_DOANH_NGHIAM_JP = TIN + "chuyen-tham-va-trao-doi-co-hoi-hop-tac-giua-doanh-nghiep-nhat-ban-va-khoa-cong-nghe-thong-tin/70996"
U_TNCS_95 = TIN + "tu-hao-tuoi-tre-sict-tai-le-ky-niem-95-nam-ngay-thanh-lap-doan-tncs-ho-chi-minh/71681"
U_NCUU_PHD_HTTT = TIN + "sinh-vien-sict-haui-tham-quan-doanh-nghiep-trai-nghiem-thuc-te-tai-cong-ty-co-phan-misa/71673"
U_NCUU_PHD_HTTT = TIN + "tour-doanh-nghiep-tai-fpt-telecom-hanh-trinh-trai-nghiem-dinh-huong-nghe-nghiep/71671"
U_NCUU_PHD_HTTT = TIN + "sinh-vien-khoa-cong-nghe-thong-tin-tham-quan-thuc-te-tai-doanh-nghiep/70601"
U_NCUU_PHD_HTTT = TIN + "sinh-vien-khoa-cong-nghe-thong-tin-tham-gia-ngay-hoi-viec-lam-2022/70610"
U_VUI_DAN_GIAN = TIN + "lien-quan-sict-tham-gia-hoi-thi-vui-hoi-dan-gian-gan-ket-yeu-thuong-chao-mung-8-3/71642"
U_NCUU_PHD_HTTT = TIN + "truong-cong-nghe-thong-tin-va-truyen-thong-to-chuc-xet-tuyen-nghien-cuu-sinh-tien-si-nganh-he-thong-thong-tin-dot-3-nam-2026/71942"
U_GS_THIEN = "https://sict.haui.edu.vn/vn/guong-sang/than-ngoc-thien-tam-guong-sinh-vien-tieu-bieu-trong-hoc-tap-va-cong-tac-doan-hoi/71243"
U_GS_NAM = "https://sict.haui.edu.vn/vn/guong-sang/nguyen-thanh-nam-niem-tu-hao-cua-nganh-khoa-hoc-may-tinh-nguoi-tre-dan-buoc-vao-ky-nguyen-ai-quoc-gia/71416"
U_GS_MANH = "https://sict.haui.edu.vn/vn/guong-sang/nguyen-van-manh-tu-hanh-trinh-hoc-thuat-den-khat-vong-kien-tao-tuong-lai-cong-nghe/71415"
U_GS_DUY = "https://sict.haui.edu.vn/vn/guong-sang/nguyen-tien-duy-giai-dac-biet-top-4-naprock-procon-nhat-ban-2023-hang-muc-competition-va-uoc-mo-tro-thanh-lap-trinh-vien-chat-luong-cao/71048"
U_GS_HUY = "https://sict.haui.edu.vn/vn/guong-sang/le-duc-huy-sinh-vien-k17-khoa-cntt-dat-giai-ba-cuoc-thi-tim-kiem-tai-nang-mc-2023/70792"
U_CSVT = "https://sict.haui.edu.vn/vn/html/co-so-vat-chat"
U_CANBO = "https://sict.haui.edu.vn/vn/html/can-bo-giang-vien"
U_AI_CENTER = "https://sict.haui.edu.vn/vn/html/trung-tam-nghien-cuu-va-ung-dung-tri-tue-nhan-tao"
U_VIDEO_CNTT = "https://sict.haui.edu.vn/vn/tuyen-sinh-dai-hoc/ctdt-cong-nghe-thong-tin-tai-truong-cong-nghe-thong-tin-va-truyen-thong-dai-hoc-cong-nghiep-ha-noi/71355"
U_VIDEO_MMTT = "https://sict.haui.edu.vn/vn/tuyen-sinh-dai-hoc/ctdt-mang-may-tinh-va-truyen-thong-du-lieu-chia-khoa-ket-noi-trong-ky-nguyen-so/71381"
U_VIDEO_DPT = "https://sict.haui.edu.vn/vn/tuyen-sinh-dai-hoc/ctdt-cong-nghe-da-phuong-tien-truong-cong-nghe-thong-tin-va-truyen-thong-dai-hoc-cong-nghiep-ha-noi/71372"
U_VIDEO_KTPM = "https://sict.haui.edu.vn/vn/tuyen-sinh-dai-hoc/gioi-thieu-ctdt-ky-thuat-phan-mem-truong-cong-nghe-thong-tin-va-truyen-thong-dai-hoc-cong-nghiep-ha-noi/71371"
U_VIDEO_HTIT = "https://sict.haui.edu.vn/vn/tuyen-sinh-dai-hoc/gioi-thieu-ve-ctdt-he-thong-thong-tin-truong-cong-nghe-thong-tin-va-truyen-thong-truong-dai-hoc-cong-nghiep-ha-noi/71340"
U_VIDEO_ATTT = "https://sict.haui.edu.vn/vn/tuyen-sinh-dai-hoc/gioi-thieu-ve-ctdt-an-toan-thong-tin-truong-cong-nghe-thong-tin-va-truyen-thong-truong-dai-hoc-cong-nghiep-ha-noi/71288"
U_VIDEO_KHMT = "https://sict.haui.edu.vn/vn/tuyen-sinh-dai-hoc/gioi-thieu-ve-ctdt-khoa-hoc-may-tinh-truong-cong-nghe-thong-tin-va-truyen-thong-sict-truong-dai-hoc-cong-nghiep-ha-noi/71284"
U_VIDEO_JIS = TIN + "recap-chuong-trinh-trao-doi-sinh-vien-jis-haui/71395"
U_VIDEO_ITF = TIN + "it-festival-2025-san-choi-bo-ich-cua-sinh-vien-truong-cong-nghe-thong-tin-va-truyen-thong/71310"
U_VIDEO_FITN_2020 = TIN + "fit-news-5-6-2020/66305"
U_VIDEO_FITN_3 = TIN + "tin-video-fit-news-thang-3-2019/61985"
U_VIDEO_FITN_9 = TIN + "tin-video-fit-news-9/61959"
U_VIDEO_FITN_8 = TIN + "tin-video-fit-news-8/61954"
U_VIDEO_FIT_MEDIA = "https://sict.haui.edu.vn/vn/cau-lac-bo/cau-lac-bo-truyen-thong-truong-cong-nghe-thong-tin-va-truyen-thong-fit-media/67474"
U_VIDEO_GIOI_THIEU = "https://sict.haui.edu.vn/vn/html/gioi-thieu"
U_VIDEO_TTCHUNG = "https://sict.haui.edu.vn/vn/html/thong-tin-chung"
MEDIA29 = "https://sict.haui.edu.vn/media/29/"
F_TKB_2024_2025 = MEDIA29 + "uffile-upload-no-title29968.xls"
P_TKB_2024_2025 = "https://sict.haui.edu.vn/vn/ke-hoach/thong-bao-ke-hoach-hoc-ky-2-nam-hoc-2024-2025-cho-sinh-vien-dai-hoc-cac-khoa/71241"
F_KH_HK1_2023 = MEDIA29 + "uffile-upload-no-title29770.pdf"
P_KH_HK1_2023 = "https://sict.haui.edu.vn/vn/ke-hoach/ke-hoach-hoc-ky-1-nam-hoc-2023-2024-cho-sinh-vien-dai-hoc-dai-hoc-khoa-18/70717"
F_TKB_HKPHU_2_2324 = MEDIA29 + "uffile-upload-no-title29844.xls"
P_TKB_HKPHU_2_2324 = "https://sict.haui.edu.vn/vn/thong-bao/ke-hoach-hoc-ky-phu-2-nam-hoc-2023-2024-cho-sinh-vien-dai-hoc-cac-khoa/70919"
F_QD721 = MEDIA29 + "uffile-upload-no-title29852.pdf"
P_QD721 = "https://sict.haui.edu.vn/vn/thong-bao/quyet-dinh-721-qd-dhcn-ban-hanh-quy-dinh-to-chuc-danh-gia-ket-qua-hoc-tap-cua-nguoi-hoc-tai-truong-dhcnhn/70933"
F_FOSSASIA = MEDIA29 + "uffile-upload-no-title29818.pdf"
P_FOSSASIA = "https://sict.haui.edu.vn/vn/thong-bao/dang-ky-tham-gia-hoi-nghi-thuong-dinh-nguon-mo-chau-a-fossasia-summit-2024-tai-ha-noi/70855"
F_DL_VL2024 = MEDIA29 + "uffile-upload-no-title29816.pdf"
P_DL_VL2024 = "https://sict.haui.edu.vn/vn/thong-bao/ngay-hoi-viec-lam-truong-dai-hoc-cong-nghiep-ha-noi-nam-2024/70853"
F_MH_DANHSACH = MEDIA29 + "uffile-upload-no-title29588.xls"
P_MH_DANHSACH = "https://sict.haui.edu.vn/vn/thong-bao/ke-hoach-to-chuc-hoat-dong-day-hoc-tuan-tu-23-03-2020-den-05-04-2020-khoa-cntt/65299"
F_TTTS_THACSI = MEDIA29 + "uffile-upload-no-title29652.pdf"
P_TTTS_THACSI = "https://sict.haui.edu.vn/vn/thong-bao/thong-bao-tuyen-sinh-dao-tao-trinh-do-thac-si-nam-2022/67501"
F_DON_THUCTAP = MEDIA29 + "uffile-upload-no-title29624.pdf"
P_DON_THUCTAP = "https://sict.haui.edu.vn/vn/thong-bao/ke-hoach-to-chuc-thuc-tap-doanh-nghiep-ngoai-truong-cho-sinh-vien-dai-hoc-khoa-13/67447"
F_HD_MODULE_TT = MEDIA29 + "uffile-upload-no-title29623.doc"
F_DON_PANASONIC = MEDIA29 + "uffile-upload-no-title29729.doc"
P_PANASONIC = "https://sict.haui.edu.vn/vn/thong-bao/chuong-trinh-hoc-bong-bac-dai-hoc-panasonic-nam-2022/70625"
F_PHIEU_DANGKY_NCKH = MEDIA29 + "uffile-upload-no-title29736.doc"
P_PHIEU_DANGKY_NCKH = "https://sict.haui.edu.vn/vn/thong-bao/dang-ky-sinh-vien-nckh/70638"
F_DON_DIGIWORLD = MEDIA29 + "uffile-upload-no-title29864.doc"
P_DIGIWORLD = "https://sict.haui.edu.vn/vn/thong-bao/hoc-bong-digiworld-uom-mam-xanh-dao-tao-ky-su-lap-trinh/70961"
F_KH_DAOTAO_1221 = MEDIA29 + "uffile-upload-no-title29613.pdf"
P_KH_DAOTAO_1221 = "https://sict.haui.edu.vn/vn/ke-hoach/ke-hoach-dao-tao-tu-ngay-06-12-2021-den-ngay-19-12-2021/67444"
F_KH_XT_TN_3_2022 = MEDIA29 + "uffile-upload-no-title29655.pdf"

# --- sha256 ảnh (12 ký tự đầu) của bài, đã tra PG media_occurrence ---------
K_TOTNGHIEP = ["2c8e496f7b48", "336df2d4eeec", "71faa185b4ae"]
K_LAB = ["1ed63a2e9927"]
K_TOURNAMENT = ["7b21b789206d", "42aa02409290", "83ce359d1361"]
K_PROCON = ["1747973c7587", "1e90e6f960e5", "2b27eee829fd"]
K_SPC = ["03c0f4314d26", "318a5dcfb404", "5b254fb71ee0"]
K_PHUNU = ["2497c1f9d1b5", "402167b1da42", "4f3987aab71a"]
K_ITSUP = ["6ebd81174398", "74cd7ba83b6d", "82e617aea846"]
K_TETAM = ["501830cfd83b", "6aa7a13fc4e4", "6e74f4d760ef"]
K_THIEN = ["153a383ac172", "1c9acf04995e", "3ed7bc72c2a0"]
K_NAM = ["1fe0831615a5", "6a121d9f3701", "b2fa50b7b234"]
K_HUY = ["1f304ccc5d4a", "77528d07e486", "91c7dc953ffd"]
K_DUY = ["102360858dfb", "2bc190eaea0d", "4cef4b130ba5"]
K_CLUB = ["0ba3420b88c4", "222179fa42b7", "2ca5260841f1"]
K_K21 = ["0233cd6cc6ad", "51625bebd359", "5b3ab1c85a42"]
K_JIS = ["1b59cf6d9051", "2280d01589a7", "2be48f909a51"]
K_GUET = ["1183c2f9b265", "1d3860c778e8", "790453175af1"]
K_MANH = None  # 71415 có 6 ảnh nhưng không tra sha — không dùng expected_media_keys cho row này

rows: list[dict] = []


def add(**kw) -> None:
    """Điền mặc định các trường còn thiếu theo schema bộ."""
    r = {"id": kw["id"], "question": kw.get("question", ""), "image": kw.get("image"),
         "case": kw["case"], "style": kw.get("style", "question"),
         "answerable": kw.get("answerable", True),
         "media_mode": kw["media_mode"], "wants_file": kw.get("wants_file", False),
         "expected_urls": kw.get("expected_urls", []),
         "expected_media_docs": kw.get("expected_media_docs", []),
         "expected_media_keys": kw.get("expected_media_keys"),
         "min_media": kw.get("min_media", 0),
         "reference": kw.get("reference", ""),
         "expected_route": kw.get("expected_route"),
         "variant_of": kw.get("variant_of"),
         "notes": kw.get("notes", ""), "status": "draft"}
    rows.append(r)


# ============================ 9 dòng draft đã duyệt ========================
for line in (ROOT / "eval" / "multimodal_v1_draft.jsonl").read_text(encoding="utf-8").splitlines():
    if line.strip():
        rows.append(json.loads(line))

# ============================ T1: 20 câu neo (golden_v2) ===================
# Lấy nguyên 20 câu fact/person/document từ golden_v2 (media_mode=none, có reference),
# đổi id thành mm-t1-…: neo chống regression + RAGAS chạy tiếp trên reference này.
G = [json.loads(x) for x in (ROOT / "eval" / "golden_v2.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
T1_IDS = ["g001", "g003", "g004", "g007", "g008", "g015", "g016", "g017", "g018", "g019",
          "g021", "g022", "g023", "g024", "g026", "g043", "g044", "g047", "g048", "g086"]
by_id = {r["id"]: r for r in G}
for i, gid in enumerate(T1_IDS, 1):
    g = by_id[gid]
    add(id=f"mm-t1-{i:02d}", question=g["question"], case=g["case"], style=g["style"],
        media_mode="none", wants_file=bool(g.get("wants_file")),
        expected_urls=g.get("expected_urls") or [], min_media=0,
        reference=g["reference"],
        notes=f"neo golden_v2 {gid} nguyên trạng (chống regression, RAGAS)")

# ============================ T2: 25 câu text→image ========================
# 11 câu có expected_media_keys (debug only-image); 14 câu còn lại chỉ expected_media_docs.
T2 = [
    # -- sự kiện 2026 (9) --
    ("mm-t2-04", "Cho xem ảnh lễ trao giải PROCON HaUI 2026", U_PROCON, K_PROCON, 3, "question",
     "PROCON HaUI 2026 công bố kết quả vòng cấp Đại học và vinh danh các đội thi xuất sắc (02/11/2026).", 6),
    ("mm-t2-05", "hình ảnh chung kết Software Product Challenge 2026", U_SPC, K_SPC, 3, "phrase",
     "Software Product Challenge 2026 vinh danh các đội thi xuất sắc tại vòng chung kết (12/10/2026).", 10),
    ("mm-t2-06", "Cho xem mấy tấm ảnh chương trình kỷ niệm Ngày Phụ nữ Việt Nam 20/10 của SICT", U_PHU_NU, K_PHUNU, 3, "chatty",
     "SICT – HaUI tổ chức chương trình kỷ niệm Ngày Phụ nữ Việt Nam 20/10 (20/10/2026).", 8),
    ("mm-t2-07", "Ảnh đội IT Supporter chăm sóc laptop cho sinh viên", U_IT_SUPPORTER, K_ITSUP, 3, "phrase",
     "IT Supporter tiếp nhận, kiểm tra và hỗ trợ sinh viên chăm sóc laptop (18/10/2026).", 7),
    ("mm-t2-08", "ảnh Tết Ấm Yêu Thương 2026", U_TET_AM, K_TETAM, 3, "no_accent",
     "Tết Ấm Yêu Thương 2026 – chương trình sẻ chia cho người khó khăn dịp Tết Bính Ngọ (06/02/2026).", 19),
    ("mm-t2-09", "Cho xem ảnh Xuân yêu thương 2026 tại Lai Châu", U_XUAN_YEU_THUONG, None, 0, "question",
     "Ngày 07/02/2026, chương trình Xuân yêu thương 2026 trao quà cho điểm trường vùng cao Lai Châu.", 14),
    ("mm-t2-10", "Có ảnh Đảng bộ Trường CNTT&TT về nguồn tại Mộc Châu không?", U_MOC_CHAU, None, 0, "question",
     "Đảng bộ bộ phận Trường CNTT&TT về nguồn tại Mộc Châu, thăm Khu di tích nơi Bác Hồ nói chuyện với cán bộ (19/01/2026).", 8),
    ("mm-t2-11", "Xem ảnh sinh viên SICT tại hội thảo quốc tế ICISN 2026", U_ICISN, None, 0, "phrase",
     "Sinh viên SICT–HaUI có nhiều công trình được chấp nhận tại Hội thảo quốc tế ICISN 2026 (22/03/2026).", 11),
    ("mm-t2-12", "ảnh hội thao SICT Tournament 2026 mùa cờ vua", U_HOI_THAO_TOURNAMENT, K_TOURNAMENT, 3, "phrase",
     "SICT Tournament 2026 có các bộ môn thể thao trong đó cờ vua thu hút nhiều kỳ thủ sinh viên.", 22),
    # -- sự kiện trước 2026 (5) --
    ("mm-t2-13", "Cho xem ảnh Ngày hội câu lạc bộ Khoa CNTT 2023", U_CLUB_DAY_2023, K_CLUB, 3, "question",
     "Ngày hội Câu lạc bộ Khoa CNTT 2023 với chủ đề Đổi mới – Sáng tạo (06/10/2023).", 13),
    ("mm-t2-14", "ảnh giao lưu sinh viên JIS Ấn Độ với sinh viên SICT", U_JIS, K_JIS, 3, "no_accent",
     "Giao lưu giữa sinh viên Đại học JIS (Ấn Độ) và sinh viên SICT – HaUI (18/06/2025).", 25),
    ("mm-t2-15", "Cho xem ảnh tân sinh viên K21 năm 2026", U_K21_DAU_TIEN, K_K21, 3, "question",
     "SICT chào đón tân sinh viên K21 năm 2026 trong những ngày đầu tiên (28/08/2026).", 12),
    ("mm-t2-16", "hinh anh hanh trinh hoc tap tai GUET Trung Quoc", U_GUET, K_GUET, 3, "no_accent",
     "Hành trình học tập, trao đổi và hợp tác tại GUET, Trung Quốc (21/10/2026).", 11),
    ("mm-t2-17", "Ảnh sinh viên SICT nhận Học bổng Tài năng Samsung STP 2025", U_SAMSUNG_STP, None, 0, "phrase",
     "Sinh viên SICT–HaUI vinh dự nhận Học bổng Tài năng Samsung STP 2025 (30/01/2026).", 9),
    # -- người (4) --
    ("mm-t2-18", "Cho xem ảnh sinh viên Thân Ngọc Thiện", U_GS_THIEN, K_THIEN, 3, "question",
     "Thân Ngọc Thiện là tấm gương sinh viên tiêu biểu trong học tập và công tác Đoàn – Hội (15/01/2025).", 9),
    ("mm-t2-19", "ảnh Nguyễn Thành Nam ngành Khoa học máy tính", U_GS_NAM, K_NAM, 3, "phrase",
     "Nguyễn Thành Nam – niềm tự hào ngành KHMT, 4 lần đạt học bổng khuyến khích học tập (31/07/2025).", 7),
    ("mm-t2-20", "Cho xem ảnh Nguyễn Tiến Duy giải NAPROCK PROCON Nhật Bản 2023", U_GS_DUY, K_DUY, 3, "question",
     "Nguyễn Tiến Duy đạt giải Đặc biệt Top 4 NAPROCK PROCON Nhật Bản 2023 (hạng mục Competition).", 7),
    ("mm-t2-21", "cho xem anh Le Duc Huy giai ba tim kiem tai nang MC 2023", U_GS_HUY, K_HUY, 3, "no_accent",
     "Lê Đức Huy (K17 CNTT) đạt giải ba cuộc thi Tìm kiếm Tài năng MC 2023.", 6),
    # -- cơ sở vật chất / tổ chức (2) --
    ("mm-t2-22", "Ảnh cơ sở vật chất Trường CNTT – nhà A1", U_CSVT, None, 0, "phrase",
     "Trụ sở Trường CNTT&TT tại Tầng 12–16, Nhà A1, ĐH Công nghiệp Hà Nội, số 296 Đường Tân Triều.", 13),
    ("mm-t2-23", "cho minh xin anh Trung tam Nghien cuu va Ung dung Tri tue nhan tao", U_AI_CENTER, None, 0, "chatty",
     "Trung tâm Nghiên cứu và Ứng dụng Trí tuệ nhân tạo của Trường CNTT&TT.", 6),
    # -- optional (2, không đòi ảnh nhưng bài có ảnh; gate phải lọc đúng bài) --
    ("mm-t2-24", "SICT Tournament 2026 có những nội dung thi gì?", U_HOI_THAO_TOURNAMENT, None, 0, "question",
     "SICT Tournament 2026 gồm các bộ môn thể thao như bóng đá, cờ vua… (20/04/2026).", 22),
    ("mm-t2-25", "Trường CNTT tổ chức xét tuyển nghiên cứu sinh tiến sĩ ngành Hệ thống thông tin thế nào?", U_NCUU_PHD_HTTT, None, 0, "question",
     "Trường CNTT&TT tổ chức xét tuyển NCS tiến sĩ ngành Hệ thống thông tin đợt 3 năm 2026 (19/10/2026).", 8),
]
for rid, q, url, keys, minm, style, ref, nimg in T2:
    # t2-24/t2-25 optional; còn lại required (required luôn đòi ≥1 ảnh)
    mode = "optional" if rid in ("mm-t2-24", "mm-t2-25") else "required"
    if mode == "required" and minm < 1:
        minm = 1
    add(id=rid, question=q, case="image", style=style, media_mode=mode,
        expected_urls=[url], expected_media_docs=[url], expected_media_keys=keys,
        min_media=minm, reference=ref,
        notes=f"doc {url.rsplit('/', 1)[-1]}, {nimg} ảnh trong sict_image_v3"
              + ("; optional: không đòi ảnh, gate phải lọc media đúng bài" if mode == "optional" else ""))

# ============================ T3: 15 câu text→video ========================
# 9 câu mới (t3-02..t3-10) + 6 câu khoét sâu từ media_v1 dạng mới (t3-11..15 biến thể/ngành khác).
T3 = [
    ("mm-t3-02", "video giới thiệu ngành Mạng máy tính và Truyền thông dữ liệu", U_VIDEO_MMTT, "question",
     "Ngành Mạng máy tính và Truyền thông dữ liệu có video giới thiệu chương trình đào tạo.", "t3-01 dạng ngành MMTT"),
    ("mm-t3-03", "có clip giới thiệu ngành Công nghệ đa phương tiện không ạ", U_VIDEO_DPT, "chatty",
     "Ngành Công nghệ đa phương tiện có video giới thiệu chương trình đào tạo.", "khoét v004 (chatty) ngành DPT"),
    ("mm-t3-04", "Video giới thiệu CTĐT Kỹ thuật phần mềm", U_VIDEO_KTPM, "abbrev",
     "Ngành Kỹ thuật phần mềm có video giới thiệu chương trình đào tạo.", "khoét v005 (abbrev)"),
    ("mm-t3-05", "Cho xem video giới thiệu ngành Hệ thống thông tin", U_VIDEO_HTIT, "question",
     "Ngành Hệ thống thông tin có video giới thiệu chương trình đào tạo.", "khoét v006"),
    ("mm-t3-06", "video gioi thieu nganh an toan thong tin", U_VIDEO_ATTT, "no_accent",
     "Ngành An toàn thông tin có video giới thiệu chương trình đào tạo.", "khoét v007 (no_accent)"),
    ("mm-t3-07", "Is there an introduction video for the Computer Science programme?", U_VIDEO_KHMT, "english",
     "Ngành Khoa học máy tính có 2 video giới thiệu chương trình đào tạo.", "khoét v008 (english, 2 video / 1 bài)"),
    ("mm-t3-08", "Bản tin video IT Festival 2025", U_VIDEO_ITF, "phrase",
     "Bản tin IT Festival 2025 là video trên kênh của Trường CNTT&TT.", "khoét v009"),
    ("mm-t3-09", "video FIT News tháng 5-6 năm 2020", U_VIDEO_FITN_2020, "question",
     "Bản tin FIT News tháng 5, 6 năm 2020 là bản tin video.", "khoét v011 dạng 2020"),
    ("mm-t3-10", "clb FIT Media có video giới thiệu không", U_VIDEO_FIT_MEDIA, "abbrev",
     "CLB Truyền thông FIT Media 2023 có video giới thiệu.", "khoét v012 (cau-lac-bo)"),
    ("mm-t3-11", "Bản tin FIT News số thứ 9", U_VIDEO_FITN_9, "phrase",
     "Bản tin FIT News số 9 là bản tin video năm 2019.", "khoét: bài chỉ có video, không ảnh"),
    ("mm-t3-12", "video tin FIT News 8", U_VIDEO_FITN_8, "abbrev",
     "Bản tin FIT News số 8 là bản tin video năm 2019.", "khoét: bài tiêu đề trống, chỉ video"),
    ("mm-t3-13", "có video recap trao đổi sinh viên JIS HaUI không", U_VIDEO_JIS, "chatty",
     "Video recap chương trình trao đổi sinh viên JIS – HaUI (2025).", "khoét v001 (recap)"),
    ("mm-t3-14", "video gioi thieu truong cong nghe thong tin", U_VIDEO_TTCHUNG, "no_accent",
     "Trường CNTT&TT có video giới thiệu tổng quan (trang Thông tin chung).", "khoét v013 (trang html)"),
    ("mm-t3-15", "Video giới thiệu khoa Công nghệ thông tin của trường điền vào đây", U_VIDEO_GIOI_THIEU, "typo",
     "Video giới thiệu Khoa CNTT – ĐH Công nghiệp Hà Nội (trang Giới thiệu).", "khoét v013 dạng khác, trang html/gioi-thieu"),
]
for rid, q, url, style, ref, note in T3:
    add(id=rid, question=q, case="video", style=style, media_mode="required",
        expected_urls=[url], expected_media_docs=[url], min_media=1, reference=ref, notes=note)

# ============================ T4: 15 câu text→file =========================
T4 = [
    ("mm-t4-02", "Tải thời khóa biểu học kỳ phụ 2 năm học 2023-2024", F_TKB_HKPHU_2_2324, P_TKB_HKPHU_2_2324, "question", "",
     "Thời khóa biểu học kỳ phụ 2 năm học 2023-2024 là file xls đính kèm thông báo kế hoạch học kỳ phụ 2 (70919)."),
    ("mm-t4-03", "kế hoạch học kỳ 1 năm học 2023-2024 khóa 18 file", F_KH_HK1_2023, P_KH_HK1_2023, "phrase", "f007 dạng 2023-2024: chỉ nêu tên, không 'tải'",
     "Kế hoạch học kỳ 1 năm học 2023-2024 cho sinh viên Đại học Khóa 18 là file PDF đính kèm trang kế hoạch (70717)."),
    ("mm-t4-04", "Quyết định 721/QĐ-ĐHCN về đánh giá kết quả học tập của người học", F_QD721, P_QD721, "phrase", "f003 dạng văn bản nêu tên",
     "Quyết định 721/QĐ-ĐHCN ban hành quy định tổ chức đánh giá kết quả học tập của người học; chi tiết trong file PDF đính kèm."),
    ("mm-t4-05", "Giới thiệu chi tiết Hội nghị FOSSASIA Summit 2024 ở đâu?", F_FOSSASIA, P_FOSSASIA, "question", "f002 dạng 'ở đâu'",
     "Giới thiệu chi tiết Hội nghị FOSSASIA Summit 2024 tại Hà Nội là file PDF đính kèm thông báo đăng ký (70855)."),
    ("mm-t4-06", "Danh sách doanh nghiệp tham gia Ngày hội việc làm 2024", F_DL_VL2024, P_DL_VL2024, "phrase", "f013 dạng danh sách",
     "Danh sách doanh nghiệp tham gia Ngày hội việc làm ĐH Công nghiệp Hà Nội 2024 là file PDF đính kèm thông báo (70853)."),
    ("mm-t4-07", "tai danh sach mon hoc hoc phan thay the", F_MH_DANHSACH, P_MH_DANHSACH, "no_accent", "f012 dạng no_accent",
     "Danh sách môn học là file xls đính kèm kế hoạch dạy học tuần 23/03–05/04/2020 của Khoa CNTT (65299)."),
    ("mm-t4-08", "Thông báo tuyển sinh đào tạo trình độ thạc sĩ năm 2022 chi tiết", F_TTTS_THACSI, P_TTTS_THACSI, "phrase", "nêu tên văn bản",
     "Thông báo tuyển sinh đào tạo trình độ thạc sĩ năm 2022: chi tiết trong file PDF đính kèm (67501)."),
    ("mm-t4-09", "đơn xin thực tập tại doanh nghiệp tải ở đâu", F_DON_THUCTAP, P_DON_THUCTAP, "question", "f002/f004 dạng 'tải ở đâu'",
     "Đơn xin thực tập tại doanh nghiệp (kèm phiếu khảo sát) là file PDF đính kèm kế hoạch thực tập K13 (67447)."),
    ("mm-t4-10", "mẫu đơn xin cấp học bổng Panasonic", F_DON_PANASONIC, P_PANASONIC, "phrase", "f004/f010 dạng 'mẫu đơn'",
     "Đơn xin cấp học bổng Panasonic (mẫu 1, dán ảnh 4x6cm) là file doc đính kèm chương trình học bổng Panasonic 2022 (70625)."),
    ("mm-t4-11", "phiếu đăng ký sinh viên nghiên cứu khoa học", F_PHIEU_DANGKY_NCKH, P_PHIEU_DANGKY_NCKH, "phrase", "f004 dạng biểu mẫu",
     "Phiếu đăng ký và thuyết minh đề tài NCKH sinh viên (nộp trước 31/8) là file doc đính kèm trang đăng ký NCKH (70638)."),
    ("mm-t4-12", "đơn đăng ký xin học bổng Digiworld", F_DON_DIGIWORLD, P_DIGIWORLD, "question", "f010 dạng học bổng",
     "Đơn đăng ký xin học bổng Digiworld là file doc đính kèm thông báo học bổng Digiworld (70961)."),
    ("mm-t4-13", "kế hoạch đào tạo tuần từ 06/12/2021 đến 19/12/2021 file", F_KH_DAOTAO_1221, P_KH_DAOTAO_1221, "phrase", "f005 dạng kế hoạch + 'file'",
     "Kế hoạch đào tạo từ 06/12/2021 đến 19/12/2021 là file PDF (67444)."),
    ("mm-t4-14", "hướng dẫn sử dụng module thông tin thực tập", F_HD_MODULE_TT, P_DON_THUCTAP, "abbrev", "f010 dạng hướng dẫn",
     "Hướng dẫn sử dụng module thông tin thực tập là file doc đính kèm kế hoạch thực tập doanh nghiệp K13 (67447)."),
    ("mm-t4-15", "thoi khoa bieu dang ky hoc tap hoc ky 2 nam hoc 2024-2025", F_TKB_2024_2025, P_TKB_2024_2025, "no_accent", "f001 dạng no_accent",
     "Thời khóa biểu đăng ký học tập học kỳ 2 năm học 2024-2025 là file xls đính kèm thông báo kế hoạch học kỳ 2 (71241)."),
]
for rid, q, furl, purl, style, note, ref in T4:
    add(id=rid, question=q, case="file", style=style, media_mode="none", wants_file=True,
        expected_urls=[furl, purl], min_media=0, reference=ref,
        notes=(note + "; " if note else "") + f"file {furl.rsplit('/', 1)[-1]}, parent {purl.rsplit('/', 1)[-1]}")

# ============================ T5: 15 câu optional / none / oos =============
T5_FACT = [
    ("mm-t5-02", "Học phí ngành Khoa học máy tính năm 2026 là bao nhiêu?", "fact", "question", [], ""),
    ("mm-t5-03", "Trường CNTT tuyển sinh hệ liên thông Cao đẳng – Đại học mấy lớp năm 2026?", "fact", "question", [], ""),
    ("mm-t5-04", "Tiếng Anh đầu vào sinh viên K21 học chương trình nào?", "fact", "question", [], "collision 'tiếng Anh'→anh/ảnh"),
    ("mm-t5-05", "đề cương môn học tại khoa CNTT tải ở đâu vậy ad", "fact", "chatty", [], "collision 'tại'→tải"),
    ("mm-t5-06", "Thầy Lê Anh Thắng giữ chức vụ gì ở khoa CNTT?", "person", "question", [], "collision 'Lê'→lễ"),
    ("mm-t5-07", "Sinh hoạt chi bộ CNTT&TT1 khi nào?", "fact", "phrase", [], ""),
    ("mm-t5-08", "what is the tuition fee per year at SICT?", "fact", "english", [], ""),
    ("mm-t5-09", "quy dinh chuan dau ra ngoai ngu cua truong", "fact", "no_accent", [], ""),
]
for i, (rid, q, case, style, urls, note) in enumerate(T5_FACT, 2):
    add(id=rid, question=q, case=case, style=style, media_mode="none", min_media=0,
        expected_urls=urls, reference="", notes=("none_clean; " if not note else "none_clean; ") + note)
# 4 câu oos (2 đòi ảnh / video — khoét x002/x004) + 2 optional đúng nghĩa
add(id="mm-t5-10", question="cho xem ảnh tháp Eiffel bằng tiếng Pháp", case="out_of_scope", style="phrase",
    media_mode="required", min_media=0, answerable=False,
    notes="oos đòi ảnh: khoét x002 — media phải rỗng (AC-R9), sufficient false")
add(id="mm-t5-11", question="video hướng dẫn nấu phở của đầu tóc Michel", case="out_of_scope", style="question",
    media_mode="required", min_media=0, answerable=False,
    notes="oos đòi video: khoét x004 — media rỗng, sufficient false")
add(id="mm-t5-12", question="cho em xin ảnh kết quả giải bóng đá vòng 30", case="out_of_scope", style="phrase",
    media_mode="required", min_media=0, answerable=False,
    notes="oos đòi ảnh; 'bóng đá' dễ dính bài thể thao trong corpus nhưng vẫn ngoài phạm vi SICT")
add(id="mm-t5-15", question="Lễ tốt nghiệp năm 2025 có bao nhiêu sinh viên nhận bằng?", case="fact", style="question",
    media_mode="none", min_media=0, expected_urls=[], reference="",
    notes="none_clean; collision 'Lễ'→le (họ Lê / lễ tốt nghiệp): phải trả chữ, không ảnh")
add(id="mm-t5-13", question="HaUI Job Fair 2026 có doanh nghiệp nào tham gia?", case="optional", style="question",
    media_mode="optional", expected_urls=by_id["g007"]["expected_urls"],
    expected_media_docs=[by_id["g007"]["expected_urls"][0]], min_media=0,
    reference="HaUI Job Fair 2026 thu hút sự tham gia của nhiều doanh nghiệp công nghệ.",
    notes="optional: bài tin sự kiện có ảnh; không bắt buộc trả ảnh")
add(id="mm-t5-14", question="Lễ tốt nghiệp năm 2025 của SICT diễn ra thế nào?", case="optional", style="question",
    media_mode="optional", expected_urls=["https://sict.haui.edu.vn/vn/tin-tuc/le-tot-nghiep-nam-2025-dau-an-thanh-xuan-trong-con-mua-mua-thu/71428"],
    expected_media_docs=["https://sict.haui.edu.vn/vn/tin-tuc/le-tot-nghiep-nam-2025-dau-an-thanh-xuan-trong-con-mua-mua-thu/71428"],
    min_media=0, reference="Lễ tốt nghiệp 2025 của SICT: hơn 750 sinh viên nhận bằng cử nhân ngày 19/8/2025.",
    notes="optional, bài 71428 có ảnh; bắt buộc text đúng")

# ============================ I1: 20 câu image-only ========================
# 20 ảnh test sẵn (5 sự kiện × 4 biến thể) — câu hỏi rỗng hoặc "đây là gì/ở đâu".
IMGS = {
    "le-tot-nghiep-2026": ("Lễ tốt nghiệp SICT 2026", U_LE_TOT_NGHIIEP_2026, K_TOTNGHIEP,
                           "SICT tổ chức lễ tốt nghiệp và trao bằng đại học chính quy K27, K29 và liên thông K22 năm 2026.",
                           {"crop50": 0.879, "q40": 0.861, "r60": 0.822}),
    "khai-truong-lab-vtit": ("Phòng lab HaUI-VTIT", U_KHAI_TRUONG_LAB, K_LAB,
                             "Trường CNTT SICT khai trương phòng lab HaUI-VTIT hợp tác với Viettel Software.",
                             {"crop50": 0.912, "q40": 0.874, "r60": 0.835}),
    "hoi-thao-sict-2026": ("Hội thao SICT Tournament 2026", U_HOI_THAO_TOURNAMENT, K_TOURNAMENT,
                           "Hội thao SICT Tournament 2026 là sân chơi thể thao cho sinh viên Trường CNTT.",
                           {"crop50": 0.908, "q40": 0.858, "r60": 0.841}),
    "ngay-hoi-viec-lam-2024": ("Ngày hội việc làm CNTT 2024", U_NGAY_HOI_VL_2024, ["106b0bc63dee"],
                               "Ngày hội việc làm CNTT 2024 kết nối doanh nghiệp với sinh viên SICT.",
                               {"crop50": 0.905, "q40": 0.87, "r60": 0.838}),
    "im-hauier-2023": ("Cuộc thi I'm HaUIer 2023", U_IM_HAUIER, ["31ed561113b3"],
                       "Cuộc thi I'm HaUIer 2023 của Trường CNTT.",
                       {"crop50": 0.879, "q40": 0.852, "r60": 0.826}),
}
SUF = {"": "", "crop50": "-crop50.jpg", "q40": "-q40.jpg", "r60": "-r60.jpg"}
N_I1 = 0
QS = ["", "", "", "", "", "Đây là sự kiện gì?", "ảnh này chụp ở đâu?", "Đây là ảnh của trường nào?"]
i1_style = {0: "question", 1: "phrase", 2: "chatty", 3: "question", 4: "phrase", 5: "question", 6: "phrase", 7: "chatty"}
DRAFT_I1 = {"mm-i1-01", "mm-i1-02"}   # draft đã có: le-tot-nghiep gốc + im-hauier crop50
for ev, (ev_name, url, keys, ref, _cos) in IMGS.items():
    for var in ("", "crop50", "q40", "r60"):
        if f"mm-i1-{N_I1 + 1:02d}" in DRAFT_I1:
            N_I1 += 1
            continue
        N_I1 += 1
        q = QS[(N_I1 - 1) % 8]
        # U8: question rỗng → required (trả cả ảnh + chữ); câu có chữ mà không có từ media
        # → router classify là none, retrieve nâng optional khi có ảnh (retriever.py)
        mode_i1 = "required" if not q.strip() else "optional"
        add(id=f"mm-i1-{N_I1:02d}", question=q, image=f"eval/images/{ev}{SUF[var]}.jpg"
            if var == "" else f"eval/images/{ev}{SUF[var]}",
            case="image", style=i1_style[(N_I1 - 1) % 8], media_mode=mode_i1,
            expected_urls=[url], expected_media_docs=[url],
            expected_media_keys=keys, min_media=1,
            reference=ref, expected_route={"inputs": ["image"], "outputs": ["image", "text"]},
            notes=f"{ev_name}; {'ảnh gốc trong index' if var == '' else 'biến thể ' + var} — cosine vs index "
                  f"{_cos.get(var, 0.967) if var else 0.967}")

# ============================ I2: 12 câu image + text → text ===============
I2 = [
    ("mm-i2-02", "Sự kiện trong ảnh này trao giải gì?", "eval/images/hoi-thao-sict-2026.jpg", U_HOI_THAO_TOURNAMENT,
     "Hội thao SICT Tournament 2026 trao giải các bộ môn thể thao cho sinh viên Trường CNTT."),
    ("mm-i2-03", "Phòng lab trong ảnh khai trương khi nào?", "eval/images/khai-truong-lab-vtit.jpg", U_KHAI_TRUONG_LAB,
     "Phòng lab HaUI-VTIT khai trương năm 2026 với Viettel Software."),
    ("mm-i2-04", "Ảnh này thuộc sự kiện nào của trường?", "eval/images/le-tot-nghiep-2026-crop50.jpg", U_LE_TOT_NGHIIEP_2026,
     "Lễ tốt nghiệp và trao bằng SICT năm 2026 cho hơn 1.000 tân thạc sĩ, kỹ sư, cử nhân."),
    ("mm-i2-05", "Buổi lễ trong ảnh có bao nhiêu sinh viên nhận bằng?", "eval/images/le-tot-nghiep-2026-q40.jpg", U_LE_TOT_NGHIIEP_2026,
     "Lễ tốt nghiệp 2026 trao bằng cho hơn 1.000 tân thạc sĩ, kỹ sư và cử nhân SICT."),
    ("mm-i2-06", "Đây là cuộc thi gì của khoa CNTT?", "eval/images/im-hauier-2023-r60.jpg", U_IM_HAUIER,
     "I'm HaUIer là cuộc thi tri ân của sinh viên CNTT năm 2023."),
    ("mm-i2-07", "Ngày hội trong ảnh có bao nhiêu cơ hội việc làm?", "eval/images/ngay-hoi-viec-lam-2024-crop50.jpg", U_NGAY_HOI_VL_2024,
     "Ngày hội việc làm CNTT 2024 mang đến gần 1000 cơ hội việc làm từ 14 doanh nghiệp."),
    ("mm-i2-08", "ảnh này là ở đâu vậy bạn", "eval/images/hoi-thao-sict-2026-crop50.jpg", U_HOI_THAO_TOURNAMENT,
     "Ảnh chụp hội thao SICT Tournament 2026 tại Trường CNTT&TT."),
    ("mm-i2-09", "Cho biết tên sự kiện trong ảnh và năm tổ chức", "eval/images/khai-truong-lab-vtit-q40.jpg", U_KHAI_TRUONG_LAB,
     "Khai trương Phòng Lab HaUI-VTIT năm 2026."),
    ("mm-i2-10", "This photo shows which event at SICT?", "eval/images/ngay-hoi-viec-lam-2024-r60.jpg", U_NGAY_HOI_VL_2024,
     "Ngày hội việc làm CNTT 2024."),
    ("mm-i2-11", "su kien trong anh nay la gi", "eval/images/le-tot-nghiep-2026-r60.jpg", U_LE_TOT_NGHIIEP_2026,
     "Lễ tốt nghiệp SICT 2026."),
    ("mm-i2-12", "anh nay chup o dau", "eval/images/im-hauier-2023-q40.jpg", U_IM_HAUIER,
     "Ảnh chụp cuộc thi I'm HaUIer 2023 của Trường CNTT."),
]
for rid, q, img, url, ref in I2:
    add(id=rid, question=q, image=img, case="image", style="no_accent" if rid == "mm-i2-11" else "question",
        media_mode="optional", expected_urls=[url], expected_media_docs=[], min_media=0,
        reference=ref, expected_route={"inputs": ["text", "image"], "outputs": ["text"]},
        notes="U5: ảnh là gợi ý, output chính là chữ; media optional (retrieve nâng none→optional khi có ảnh)")

# ============================ I3: 10 câu image + text → image ==============
I3 = [
    ("mm-i3-02", "cho xem thêm ảnh cùng sự kiện này", "eval/images/hoi-thao-sict-2026-crop50.jpg", U_HOI_THAO_TOURNAMENT, K_TOURNAMENT),
    ("mm-i3-03", "Cho xem thêm các ảnh khác của lễ tốt nghiệp này", "eval/images/le-tot-nghiep-2026.jpg", U_LE_TOT_NGHIIEP_2026, K_TOTNGHIEP),
    ("mm-i3-04", "ảnh này trong phòng lab à, cho xem thêm ảnh phòng lab", "eval/images/khai-truong-lab-vtit-q40.jpg", U_KHAI_TRUONG_LAB, K_LAB),
    ("mm-i3-05", "xem thêm ảnh của ngày hội này", "eval/images/ngay-hoi-viec-lam-2024.jpg", U_NGAY_HOI_VL_2024, ["106b0bc63dee"]),
    ("mm-i3-06", "cho xem mấy tấm khác của cuộc thi này", "eval/images/im-hauier-2023-crop50.jpg", U_IM_HAUIER, ["31ed561113b3"]),
    ("mm-i3-07", "show more photos from this event", "eval/images/le-tot-nghiep-2026-q40.jpg", U_LE_TOT_NGHIIEP_2026, K_TOTNGHIEP),
    ("mm-i3-08", "anh khac cung ngay hoi", "eval/images/ngay-hoi-viec-lam-2024-q40.jpg", U_NGAY_HOI_VL_2024, ["106b0bc63dee"]),
    ("mm-i3-09", "cho xem tiep anh hoi thao", "eval/images/hoi-thao-sict-2026-q40.jpg", U_HOI_THAO_TOURNAMENT, K_TOURNAMENT),
    ("mm-i3-10", "cho em xin thêm ảnh lễ này với ạ", "eval/images/le-tot-nghiep-2026-crop50.jpg", U_LE_TOT_NGHIIEP_2026, K_TOTNGHIEP),
    ("mm-i3-11", "xem them anh cuoc thi", "eval/images/im-hauier-2023-r60.jpg", U_IM_HAUIER, ["31ed561113b3"]),
]
for rid, q, img, url, keys in I3:
    add(id=rid, question=q, image=img, case="image", style="chatty" if "ạ" in q or "em" in q else "phrase",
        media_mode="required", expected_urls=[url], expected_media_docs=[url],
        expected_media_keys=keys, min_media=1,
        reference=f"Ảnh khác của cùng sự kiện trong bài {url.rsplit('/', 1)[-1]}.",
        expected_route={"inputs": ["text", "image"], "outputs": ["image"]},
        notes="U6: 'cho xem thêm ảnh' — ảnh giống không cần bài chữ top; đo nhánh miễn coupled")

# ============================ I4: 8 câu image + text → text + image ========
I4 = [
    ("mm-i4-02", "Sự kiện này khi nào, cho xem thêm ảnh", "eval/images/le-tot-nghiep-2026.jpg", U_LE_TOT_NGHIIEP_2026, K_TOTNGHIEP),
    ("mm-i4-03", "Phòng lab này hợp tác với đơn vị nào, cho xem thêm ảnh khai trương", "eval/images/khai-truong-lab-vtit.jpg", U_KHAI_TRUONG_LAB, K_LAB),
    ("mm-i4-04", "Đây là hội thao gì, cho em xem thêm ảnh với", "eval/images/hoi-thao-sict-2026.jpg", U_HOI_THAO_TOURNAMENT, K_TOURNAMENT),
    ("mm-i4-05", "Ngày hội này có bao nhiêu doanh nghiệp, xem thêm ảnh luôn", "eval/images/ngay-hoi-viec-lam-2024.jpg", U_NGAY_HOI_VL_2024, ["106b0bc63dee"]),
    ("mm-i4-06", "Cuộc thi trong ảnh là gì, cho xem thêm ảnh khác", "eval/images/im-hauier-2023-crop50.jpg", U_IM_HAUIER, ["31ed561113b3"]),
    ("mm-i4-07", "When was this event held? Show more photos.", "eval/images/khai-truong-lab-vtit-crop50.jpg", U_KHAI_TRUONG_LAB, K_LAB),
    ("mm-i4-08", "su kien nay to chuc luc nao, cho xem them anh", "eval/images/hoi-thao-sict-2026-r60.jpg", U_HOI_THAO_TOURNAMENT, K_TOURNAMENT),
    ("mm-i4-09", "Đây là phòng gì, cho xem thêm ảnh của ngày khai trương", "eval/images/khai-truong-lab-vtit-r60.jpg", U_KHAI_TRUONG_LAB, K_LAB),
]
for rid, q, img, url, keys in I4:
    add(id=rid, question=q, image=img, case="image", style="question",
        media_mode="required", expected_urls=[url], expected_media_docs=[url],
        expected_media_keys=keys, min_media=1,
        reference=f"Thông tin sự kiện/người trong bài {url.rsplit('/', 1)[-1]} kèm ảnh của cùng bài.",
        expected_route={"inputs": ["text", "image"], "outputs": ["text", "image"]},
        notes="U7: chữ + ảnh cùng lúc")

# ============================ S: 10 câu style phủ chéo =====================
S_ROWS = [
    ("mm-s-01", "anh le tot nghiep nam 2026", U_LE_TOT_NGHIIEP_2026, K_TOTNGHIEP, "no_accent", "t2-01", "image", "required", 3),
    ("mm-s-02", "vidéo giới thiêu ngành hệ thông thông tin", U_VIDEO_HTIT, None, "typo", "t3-05", "video", "required", 1),
    ("mm-s-03", "tai thoi khoa bieu dang ky hoc tap hk2 2024-2025", F_TKB_2024_2025, None, "no_accent", "t4-01 dạng TKB", "file", "none", 0),
    ("mm-s-04", "Cho xem mấy ảnh Tết Âm Yêu Thương 2026 được không ạ", U_TET_AM, K_TETAM, "chatty", "t2-08", "image", "required", 3),
    ("mm-s-05", "Photos of SICT Tournament 2026", U_HOI_THAO_TOURNAMENT, K_TOURNAMENT, "english", "t2-12", "image", "required", 3),
    ("mm-s-06", "hoc phi nganh cntt 2026 bn", None, None, "no_accent", "t5-02", "none", "none", 0),
    ("mm-s-07", "Cho xin video gioi thieu nganh ATTT", U_VIDEO_ATTT, None, "abbrev", "t3-06", "video", "required", 1),
    ("mm-s-08", "ảnh trưởng khoa Mạng máy tính và Truyền thông", "https://sict.haui.edu.vn/vn/html/can-bo-giang-vien/pgs-ts-tran-tien-dung", None, "question", "person canbo", "image", "required", 1),
    ("mm-s-09", "mẫu đơn đăng ký tham gia học bổng KOVA", "https://sict.haui.edu.vn/media/29/uffile-upload-no-title29734.doc", None, "phrase", "t4-10 dạng khác", "file", "none", 0),
    ("mm-s-10", "ảnh ngày hội tuyển thành viên câu lạc bộ khoa CNTT", "https://sict.haui.edu.vn/vn/tin-tuc/chao-mung-tan-thanh-vien-cac-cau-lac-bo-doi-nhom/66353", None, "phrase", "m006 dạng khác", "image", "required", 6),
]
for rid, q, url, keys, style, vo, kind, mode, minm in S_ROWS:
    file_url = url if kind == "file" else None
    if kind == "file":
        add(id=rid, question=q, case="file", style=style, media_mode=mode, wants_file=True,
            expected_urls=[url], min_media=0, reference="", variant_of=None,
            notes=f"S phủ chéo; {vo}; file {url.rsplit('/', 1)[-1]}")
    elif kind == "none":
        add(id=rid, question=q, case="none", style=style, media_mode="none", min_media=0,
            notes="S phủ chéo; none_clean")
    else:
        add(id=rid, question=q, case=kind, style=style, media_mode=mode,
            expected_urls=[url], expected_media_docs=[url], expected_media_keys=keys, min_media=minm,
            reference="", variant_of=None,
            notes=f"S phủ chéo; {vo}; bài {url.rsplit('/', 1)[-1]}")

# Các style S là before/after của các dòng trong cùng bộ (variant_lift):
_variant_map = {
    "mm-s-01": "mm-t2-01", "mm-s-02": "mm-t3-05", "mm-s-03": "mm-t4-01",
    "mm-s-04": "mm-t2-08", "mm-s-05": "mm-t2-12", "mm-s-06": "mm-t5-02",
    "mm-s-07": "mm-t3-06", "mm-s-08": "mm-t2-22", "mm-s-09": "mm-t4-10",
    "mm-s-10": "mm-t2-06",
}
for _r in rows:
    if _r["id"] in _variant_map:
        _r["variant_of"] = _variant_map[_r["id"]]

# ============================ Ghi file =====================================
# hợp lệ hoá
ids = [r["id"] for r in rows]
assert len(ids) == len(set(ids)), "trùng id"
assert len(rows) == 150, f"cần 150 dòng, có {len(rows)}"
from collections import Counter

grp = Counter()
for r in rows:
    g = r["id"].split("-")[1]
    grp[g] += 1
print("phân bổ:", dict(sorted(grp.items())))
img_rows = [r for r in rows if r.get("image")]
print("câu có ảnh:", len(img_rows))
out = ROOT / "eval" / "multimodal_v1.jsonl"
with out.open("w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"→ {out} ({len(rows)} dòng)")
