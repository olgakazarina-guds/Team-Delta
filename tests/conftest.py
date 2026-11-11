from __future__ import annotations

import tarfile
import textwrap
from pathlib import Path

import pytest

from core.config import reset_settings


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path: Path, monkeypatch):
    """Keep every test out of the repository's data directory."""
    monkeypatch.setenv("LMS_CONVERTER_DATA_DIR", str(tmp_path / "data"))
    reset_settings()
    yield
    reset_settings()


def _write_tree(root: Path, files: dict[str, str | bytes]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(textwrap.dedent(content), encoding="utf-8")


def _tar_tree(source: Path, archive_path: Path) -> Path:
    with tarfile.open(archive_path, "w:gz") as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.add(path, arcname=str(path.relative_to(source)))
    return archive_path


@pytest.fixture
def openedx_archive(tmp_path: Path) -> Path:
    root = tmp_path / "openedx-src"
    files = {
        "course.xml": """\
            <course url_name="course1" org="TestOrg" course="TEST101" />
        """,
        "course/course1.xml": """\
            <course display_name="Test Open edX Course">
              <chapter url_name="ch1" />
            </course>
        """,
        "chapter/ch1.xml": """\
            <chapter display_name="Chapter One">
              <sequential url_name="seq1" />
            </chapter>
        """,
        "sequential/seq1.xml": """\
            <sequential display_name="Sequential One">
              <vertical url_name="vert1" />
            </sequential>
        """,
        "vertical/vert1.xml": """\
            <vertical display_name="Vertical One">
              <html url_name="html1" display_name="Intro HTML" />
              <video url_name="vid1" display_name="Lecture Video" />
              <problem url_name="prob1" display_name="Knowledge Check" />
              <discussion url_name="disc1" display_name="Class Forum" />
              <openassessment url_name="ora1" display_name="Peer Essay" />
            </vertical>
        """,
        "html/html1.xml": """\
            <html display_name="Intro HTML" filename="html1.html" />
        """,
        "html/html1.html": "<p>Hello from the HTML component.</p>",
        "video/vid1.xml": """\
            <video display_name="Lecture Video" youtube_id_1_0="abc12345678" />
        """,
        "problem/prob1.xml": """\
            <problem display_name="Knowledge Check">
              <multiplechoiceresponse>
                <label>Pick one</label>
                <choicegroup type="MultipleChoice">
                  <choice correct="true">A</choice>
                  <choice correct="false">B</choice>
                </choicegroup>
              </multiplechoiceresponse>
              <choiceresponse>
                <label>Pick many</label>
                <checkboxgroup>
                  <choice correct="true">X</choice>
                  <choice correct="true">Y</choice>
                  <choice correct="false">Z</choice>
                </checkboxgroup>
              </choiceresponse>
              <stringresponse answer="42" type="ci">
                <label>Short answer</label>
                <textline size="20" />
              </stringresponse>
              <numericalresponse answer="3.14">
                <label>Numerical answer</label>
                <formulaequationinput />
              </numericalresponse>
            </problem>
        """,
        "discussion/disc1.xml": """\
            <discussion display_name="Class Forum">
              <description>Discuss the lecture here.</description>
            </discussion>
        """,
        "openassessment/ora1.xml": """\
            <openassessment display_name="Peer Essay">
              <prompts>
                <prompt>
                  <description>Write a short essay about the lecture.</description>
                </prompt>
              </prompts>
            </openassessment>
        """,
        "static/handout.pdf": b"%PDF-1.4 fixture handout",
    }
    _write_tree(root, files)
    return _tar_tree(root, tmp_path / "openedx.tar.gz")


@pytest.fixture
def moodle_archive(tmp_path: Path) -> Path:
    root = tmp_path / "moodle-src"
    content_hash = "a" * 40
    files = {
        "moodle_backup.xml": """\
            <moodle_backup>
              <information>
                <name>backup.mbz</name>
                <contents>
                  <activities>
                    <activity><moduleid>2</moduleid><sectionid>1</sectionid><modulename>page</modulename><title>Page</title><directory>activities/page_2</directory></activity>
                    <activity><moduleid>3</moduleid><sectionid>1</sectionid><modulename>quiz</modulename><title>Quiz</title><directory>activities/quiz_3</directory></activity>
                    <activity><moduleid>4</moduleid><sectionid>1</sectionid><modulename>resource</modulename><title>Resource</title><directory>activities/resource_4</directory></activity>
                    <activity><moduleid>5</moduleid><sectionid>1</sectionid><modulename>scorm</modulename><title>SCORM</title><directory>activities/scorm_5</directory></activity>
                    <activity><moduleid>6</moduleid><sectionid>1</sectionid><modulename>url</modulename><title>Video Link</title><directory>activities/url_6</directory></activity>
                    <activity><moduleid>7</moduleid><sectionid>1</sectionid><modulename>resource</modulename><title>Video File</title><directory>activities/resource_7</directory></activity>
                  </activities>
                  <sections>
                    <section><sectionid>1</sectionid><title>Week One</title><directory>sections/section_1</directory></section>
                  </sections>
                  <course><courseid>1</courseid><title>Test Moodle Course</title><directory>course</directory></course>
                </contents>
              </information>
            </moodle_backup>
        """,
        "course/course.xml": """\
            <course id="1">
              <shortname>MoodleTest</shortname>
              <fullname>Test Moodle Course</fullname>
              <lang>en</lang>
            </course>
        """,
        "sections/section_1/section.xml": """\
            <section id="1">
              <number>0</number>
              <name>Week One</name>
              <summary>Welcome</summary>
              <sequence>2,3,4,5,6,7</sequence>
            </section>
        """,
        "activities/page_2/page.xml": """\
            <page id="2">
              <name>Page</name>
              <intro>Intro</intro>
              <content>&lt;p&gt;Page content&lt;/p&gt;</content>
            </page>
        """,
        "activities/quiz_3/quiz.xml": """\
            <quiz id="3">
              <name>Quiz</name>
              <intro>Quiz intro</intro>
              <question_instances>
                <question_instance><questionid>101</questionid></question_instance>
                <question_instance><questionid>102</questionid></question_instance>
                <question_instance><questionid>103</questionid></question_instance>
                <question_instance><questionid>104</questionid></question_instance>
              </question_instances>
            </quiz>
        """,
        "activities/resource_4/resource.xml": """\
            <resource id="4"><name>Resource</name><intro>Resource intro</intro></resource>
        """,
        "activities/resource_4/inforef.xml": """\
            <inforef><fileref><file><id>10</id></file></fileref></inforef>
        """,
        "activities/scorm_5/scorm.xml": """\
            <scorm id="5"><name>SCORM</name><version>SCORM_1.2</version><launch>index.html</launch></scorm>
        """,
        "activities/scorm_5/package.zip": b"PK\x05\x06" + b"\x00" * 18,
        "activities/url_6/url.xml": """\
            <url id="6"><name>Video Link</name><externalurl>https://www.youtube.com/watch?v=xyz12345678</externalurl></url>
        """,
        "activities/resource_7/resource.xml": """\
            <resource id="7"><name>Video File</name><intro>Video resource</intro></resource>
        """,
        "activities/resource_7/inforef.xml": """\
            <inforef><fileref><file><id>11</id></file></fileref></inforef>
        """,
        "files.xml": f"""\
            <files>
              <file id="10">
                <contenthash>{content_hash}</contenthash>
                <filename>doc.pdf</filename>
                <filepath>/</filepath>
                <mimetype>application/pdf</mimetype>
              </file>
              <file id="11">
                <contenthash>{"b" * 40}</contenthash>
                <filename>clip.mp4</filename>
                <filepath>/</filepath>
                <mimetype>video/mp4</mimetype>
              </file>
            </files>
        """,
        f"files/{content_hash[:2]}/{content_hash}": b"%PDF-1.4 test",
        f"files/bb/{'b' * 40}": b"fake video bytes",
        "questions.xml": """\
            <question_categories>
              <question_category id="1">
                <questions>
                  <question id="101">
                    <name>MC</name>
                    <questiontext>Pick one</questiontext>
                    <defaultmark>2</defaultmark>
                    <qtype>multichoice</qtype>
                    <plugin_qtype_multichoice_question>
                      <answers>
                        <answer id="1"><answertext>A</answertext><fraction>1</fraction></answer>
                        <answer id="2"><answertext>B</answertext><fraction>0</fraction></answer>
                      </answers>
                      <multichoice><single>1</single></multichoice>
                    </plugin_qtype_multichoice_question>
                  </question>
                  <question id="102">
                    <name>TF</name>
                    <questiontext>True or false</questiontext>
                    <defaultmark>1</defaultmark>
                    <qtype>truefalse</qtype>
                    <plugin_qtype_truefalse_question>
                      <answers>
                        <answer id="3"><answertext>True</answertext><fraction>1</fraction></answer>
                        <answer id="4"><answertext>False</answertext><fraction>0</fraction></answer>
                      </answers>
                    </plugin_qtype_truefalse_question>
                  </question>
                  <question id="103">
                    <name>SA</name>
                    <questiontext>Short answer</questiontext>
                    <defaultmark>1</defaultmark>
                    <qtype>shortanswer</qtype>
                    <plugin_qtype_shortanswer_question>
                      <answers>
                        <answer id="5"><answertext>Answer</answertext><fraction>1</fraction></answer>
                      </answers>
                    </plugin_qtype_shortanswer_question>
                  </question>
                  <question id="104">
                    <name>NUM</name>
                    <questiontext>Numerical</questiontext>
                    <defaultmark>1</defaultmark>
                    <qtype>numerical</qtype>
                    <plugin_qtype_numerical_question>
                      <answers>
                        <answer id="6"><answertext>3.14</answertext><fraction>1</fraction><tolerance>0.01</tolerance></answer>
                      </answers>
                    </plugin_qtype_numerical_question>
                  </question>
                </questions>
              </question_category>
            </question_categories>
        """,
    }
    _write_tree(root, files)
    return _tar_tree(root, tmp_path / "moodle.mbz")
