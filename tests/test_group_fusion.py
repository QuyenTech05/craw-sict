"""RRF nhóm text/media và provenance của từng tín hiệu."""

from sict_crawler.service.retrieval.fusion import RankedList, fuse_media_lists, fuse_text_lists


def test_text_ranking_is_independent_of_media_candidates():
    a = {"_pid": "a", "document_id": 4, "title": "Đúng", "score": .4,
         "url": "https://example.org/a", "chunk_id": "a"}
    b = {"_pid": "b", "document_id": 5, "title": "Khác", "score": .95,
         "url": "https://example.org/b", "chunk_id": "b"}
    text_lists = [RankedList("bm25", (a, b)), RankedList("dense", (b, a)),
                  RankedList("name_bm25", (a,))]
    first = fuse_text_lists(text_lists)
    media = fuse_media_lists([RankedList("image", tuple(
        {"media_key": f"picture-{i}", "url": f"https://example.org/p/{i}", "score": .99}
        for i in range(20)))])
    assert first[0].candidate_id == "text:a"
    assert first == fuse_text_lists(text_lists)
    assert len(media) == 20
    assert set(first[0].leg_ranks) == {("bm25", 1), ("dense", 2), ("name_bm25", 1)}
    assert first[0].phrase_match is True
    assert first[0].dense_score == .4


def test_same_video_frames_in_one_leg_vote_once():
    frames = [{"media_key": f"frame-{i}", "video_url": "https://example.org/video",
               "kind": "video_frame", "score": 0.9, "url": "https://example.org/post"}
              for i in range(3)]
    hits = fuse_media_lists([RankedList("image", tuple(frames))])
    assert len(hits) == 1
    assert hits[0].rrf_score == 1 / 61
    assert hits[0].leg_ranks == (("image", 1),)


def test_different_media_legs_can_vote_for_same_video():
    frame = {"media_key": "keyframe", "video_id": "123", "kind": "video_frame",
             "url": "https://example.org/post", "raw_score": .87}
    caption = {"media_key": "subtitle", "video_id": "123", "kind": "video_frame",
               "url": "https://example.org/post", "caption": "Lời thoại"}
    fused = fuse_media_lists([RankedList("image", (frame,)), RankedList("caption", (caption,))])
    assert len(fused) == 1
    assert fused[0].rrf_score == 2 / 61
    assert fused[0].raw_score == .87


def test_video_fusion_preserves_caption_from_later_leg():
    frame = {"media_key": "frame", "video_id": "abc", "kind": "video_frame",
             "url": "https://example.org/post", "score": .91, "raw_score": .91}
    caption = {"media_key": "caption", "video_id": "abc", "kind": "video_frame",
               "url": "https://example.org/post", "caption": "Phụ đề sự kiện",
               "ocr_text": "Chữ trên khung hình"}

    candidate = fuse_media_lists([RankedList("image", (frame,)),
                                  RankedList("caption", (caption,))])[0]

    assert candidate.media_key == "frame"
    assert candidate.to_hit()["caption"] == "Phụ đề sự kiện"
    assert candidate.to_hit()["ocr_text"] == "Chữ trên khung hình"
    assert candidate.rrf_score == 2 / 61
