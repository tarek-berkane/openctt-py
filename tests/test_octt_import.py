"""Original OpenCTT files (XML) open as ordinary documents."""
import os
import tempfile

from octt import io
from octt.rules.hard import violations

XML = """<?xml version="1.0" encoding="utf-8"?>
<open_course_timetabler document_type="1" version="1.0">
 <edu_institution_name>École X</edu_institution_name><school_year>2024/25</school_year>
 <incl_days><day_index>1</day_index><day_index>2</day_index><day_index>4</day_index></incl_days>
 <incl_terms><term index="2">09:00-09:45</term><term index="1">08:00-08:45</term></incl_terms>
 <teachers>
  <teacher id="7"><name>Ann</name><last_name>Lee</last_name><title/><edu_rank/><extid/>
   <spec_slots type="allowed"><spec_slot><day_index>1</day_index><term_index>1</term_index></spec_slot></spec_slots></teacher>
  <teacher id="9"><name>Bob</name><last_name/><title/><edu_rank/><extid/><allowed_classrooms><classroom_id>3</classroom_id></allowed_classrooms></teacher>
 </teachers>
 <classrooms><classroom id="3"><name>R1</name><extid/><capacity>30</capacity>
   <spec_slots type="unallowed"><spec_slot><day_index>4</day_index><term_index>2</term_index></spec_slot></spec_slots></classroom></classrooms>
 <edu_program_groups><edu_program_group><name>G5</name><extid/>
  <edu_programs><edu_program id="40"><name>5A</name><code/><semester/><extid/><courses>
   <course id="11"><name>Math</name><short_name/><course_type/><num_of_lessons_per_week>2</num_of_lessons_per_week><num_of_enrolled_students>25</num_of_enrolled_students><group_name/><teacher_id>7</teacher_id><extid/>
     <to_hold_together_with><course_id>12</course_id></to_hold_together_with></course>
   <course id="12"><name>Art</name><short_name/><course_type/><num_of_lessons_per_week>2</num_of_lessons_per_week><num_of_enrolled_students>25</num_of_enrolled_students><group_name>A</group_name><teacher_id>9</teacher_id><extid/></course>
  </courses></edu_program></edu_programs></edu_program_group></edu_program_groups>
 <activities><lessons_in_tt><lesson_in_tt><course_id>11</course_id><day_index>2</day_index><term_index>2</term_index><classroom_id>3</classroom_id></lesson_in_tt></lessons_in_tt></activities>
 <soft_constraints>
  <sc_eps><sc_ep_base><max_hours_continuously>6</max_hours_continuously><max_hours_daily>5</max_hours_daily><max_days_per_week>6</max_days_per_week><gap_indicator>4</gap_indicator><preferred_start_time_period>1</preferred_start_time_period></sc_ep_base>
   <sc_ep sc_ep_id="40"><max_hours_daily>3</max_hours_daily></sc_ep></sc_eps>
  <sc_teachers><sc_teacher_base><max_hours_continuously>4</max_hours_continuously><max_hours_daily>4</max_hours_daily><max_days_per_week>1</max_days_per_week></sc_teacher_base>
   <sc_teacher sc_teacher_id="9"><max_days_per_week>3</max_days_per_week></sc_teacher></sc_teachers>
  <sc_courses><sc_course sc_course_id="12"><min_block_size>2</min_block_size><min_num_of_blocks>1</min_num_of_blocks><max_num_of_blocks>1</max_num_of_blocks></sc_course></sc_courses>
 </soft_constraints>
</open_course_timetabler>"""


def load(xml=XML):
    with tempfile.NamedTemporaryFile("w", suffix=".octt", delete=False, encoding="utf-8") as f:
        f.write(xml)
    try:
        return io.load(f.name)
    finally:
        os.unlink(f.name)


def test_original_file_imports_with_its_structure():
    d = load()
    assert (d.institution, d.year, d.days, d.terms) == ("École X", "2024/25", ["Mon", "Tue", "Thu"], ["08:00-08:45", "09:00-09:45"])
    assert {t.id: t.name for t in d.teachers.values()} == {7: "Ann Lee", 9: "Bob"}
    assert d.teachers[7].blocked == {(1, 0), (1, 1), (1, 2), (0, 1), (0, 2)}  # 'allowed' lists the one free slot (Mon, 1st)
    assert d.teachers[9].allowed_rooms == {3} and d.rooms[3].blocked == {(1, 2)}  # Thu = day 4 -> third included day
    assert d.rooms[3].capacity == 30 and d.eps[1].name == "5A" and d.epgs[1].name == "G5"
    c = d.courses
    assert (c[11].lessons, c[11].students, c[12].group, c[12].ep_id) == (2, 25, "A", 1)
    assert c[11].hold_together == [12] and c[12].hold_together == [11]
    assert [(p.course_id, p.term, p.day, p.room_id) for p in d.placements] == [(11, 1, 1, 3)]


def test_original_soft_constraints_become_overrides():
    d = load()
    assert d.params == {"student_daily": 5, "teacher_days": 1} and d.eps[1].limits["student_daily"] == 3
    assert d.teachers[9].limits == {"teacher_days": 3} and d.courses[12].blocks == [2, 1, 1]


def test_bad_xml_is_a_clean_error():
    for bad in ("<a>", "<other/>", "<open_course_timetabler><teachers><teacher/></teachers></open_course_timetabler>"):
        try:
            load(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_"):
            fn()
            print("ok", n)
