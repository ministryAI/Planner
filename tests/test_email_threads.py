"""Deterministic email thread facts: grouping, order, who wrote last. Run: python3 -m unittest discover tests"""
import os
import sys
import tempfile
import unittest

os.environ.setdefault("STEWARD_HOME", tempfile.mkdtemp())
os.environ.pop("DIANA_WORK_EMAIL_ADDRESS", None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import steward_server as S  # noqa: E402

ME = "Justin.Polsley@usc.salvationarmy.org"
CHRIS = "Christopher.White@usc.salvationarmy.org"
CONV = "AAQkADcyM2M4NjFiLWIzOTktNDJhNS05ZDE3LTIwNzM0NDU0Y2MzMQAQALuGrJ2yskXbtRxpC-HLBj4="


def msg(when, frm, to, subject, preview="", folder="inbox", conv=CONV, **extra):
    m = {"conversationId": conv, "receivedDateTime": when, "from": frm, "toRecipients": to, "subject": subject,
         "bodyPreview": preview, "sourceFolder": folder, "id": when + frm}
    m.update(extra)
    if folder is None:
        del m["sourceFolder"]
    return m


def threads(feed):
    me, th = S._mail_threads(S._mail_normalize(feed))
    return me, {t["subject"]: t for t in th}


class ChristopherWhite(unittest.TestCase):
    inbound = msg("2026-09-18T20:18:00+00:00", CHRIS, ME, "Red Shield Clubs in GLD?", "Do we have Red Shield Clubs in GLD?")
    reply = msg("2026-09-21T14:18:48+00:00", ME, CHRIS, "Re: Red Shield Clubs in GLD?", "Yes, three of them.", folder="sent")

    def check(self, feed):
        _, th = threads(feed)
        t = th["Red Shield Clubs in GLD?"]
        self.assertEqual(t["count"], 2)
        self.assertEqual(t["state"], "RESPONDED")
        self.assertTrue(t["last_from_me"])
        self.assertEqual([m["who"] for m in t["recent"]], ["Christopher.White@usc.salvationarmy.org".lower(), "you"])

    def test_as_exported(self):
        self.check([self.inbound, self.reply])

    def test_input_order_does_not_matter(self):
        self.check([self.reply, self.inbound])

    def test_sent_record_missing_source_folder(self):
        self.check([self.inbound, {**self.reply, "sourceFolder": ""}, msg("2026-09-20T10:00:00+00:00", "x@y.org", ME, "Other", conv="c2")])

    def test_sent_folder_named_differently(self):
        for name in ("Sent Items", "sentitems", "SENT"):
            self.check([self.inbound, {**self.reply, "sourceFolder": name}])

    def test_own_address_from_setting(self):
        os.environ["DIANA_WORK_EMAIL_ADDRESS"] = ME
        try:
            self.check([self.inbound, {k: v for k, v in self.reply.items() if k != "sourceFolder"}])
        finally:
            del os.environ["DIANA_WORK_EMAIL_ADDRESS"]


class ReplyState(unittest.TestCase):
    def test_they_wrote_last_is_only_potential(self):
        """Them: send the doc? / Me: attached / Them: Thanks!  → they wrote last; Diana decides it needs no reply."""
        _, th = threads([
            msg("2026-10-01T09:00:00Z", CHRIS, ME, "Doc", "Can you send the document?"),
            msg("2026-10-01T10:00:00Z", ME, CHRIS, "Re: Doc", "Sure, attached.", folder="sent"),
            msg("2026-10-01T11:00:00Z", CHRIS, ME, "Re: Doc", "Thanks!"),
        ])
        t = th["Doc"]
        self.assertEqual(t["state"], "POTENTIALLY_NEEDS_REPLY")
        self.assertEqual(t["followups"], 0)
        self.assertEqual([m["preview"] for m in t["recent"]], ["Can you send the document?", "Sure, attached.", "Thanks!"])

    def test_unanswered_followups_counted(self):
        _, th = threads([
            msg("2026-10-01T09:00:00Z", CHRIS, ME, "Q", "Can we meet?"),
            msg("2026-10-02T09:00:00Z", CHRIS, ME, "Re: Q", "Following up?"),
            msg("2026-09-30T09:00:00Z", ME, "a@b.org", "Other", "hi", folder="sent", conv="other"),
        ])
        self.assertEqual(th["Q"]["state"], "POTENTIALLY_NEEDS_REPLY")
        self.assertEqual(th["Q"]["followups"], 1)
        self.assertTrue(th["Q"]["ask"])

    def test_same_timestamp_reply_sorts_after(self):
        _, th = threads([msg("2026-10-01T09:00:00Z", ME, CHRIS, "Re: T", "ok", folder="sent"), msg("2026-10-01T09:00:00Z", CHRIS, ME, "T", "?")])
        self.assertEqual(th["T"]["state"], "RESPONDED")

    def test_no_conversation_id_groups_by_subject(self):
        _, th = threads([msg("2026-10-01T09:00:00Z", CHRIS, ME, "Budget", "Numbers?", conv=""), msg("2026-10-02T09:00:00Z", ME, CHRIS, "RE: Budget", "Sent.", folder="sent", conv="")])
        self.assertEqual(th["Budget"]["count"], 2)
        self.assertEqual(th["Budget"]["state"], "RESPONDED")


if __name__ == "__main__":
    unittest.main()


class ReplyThenThanks(unittest.TestCase):
    """You replied, then someone on the thread wrote back: the reply must still be stated, and a thank-you flagged."""
    CHAROL = "Charol.Smith@usc.salvationarmy.org"

    def feed(self, last_preview):
        return [ChristopherWhite.inbound, ChristopherWhite.reply,
                msg("2026-09-22T09:00:00+00:00", self.CHAROL, CHRIS, "RE: Red Shield Clubs in GLD?", last_preview)]

    def test_thanks_after_reply(self):
        _, th = threads(self.feed("Thanks so much, Justin!"))
        t = th["Red Shield Clubs in GLD?"]
        self.assertEqual(t["state"], "POTENTIALLY_NEEDS_REPLY")
        self.assertTrue(t["ack"])
        self.assertTrue(t["replied_ts"])
        self.assertEqual([m["who"] for m in t["after_reply"]], [self.CHAROL.lower()])
        self.assertLess(t["score"], 40)

    def test_question_after_reply_is_not_ack(self):
        _, th = threads(self.feed("Thanks! Which corps are they at?"))
        self.assertFalse(th["Red Shield Clubs in GLD?"]["ack"])

    def test_never_replied(self):
        _, th = threads([ChristopherWhite.inbound])
        t = th["Red Shield Clubs in GLD?"]
        self.assertIsNone(t["replied_ts"])
        self.assertEqual(t["after_reply"], [])
