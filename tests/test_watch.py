"""Where a film or series can be watched. "Play Inception" used to open Netflix whatever the film was."""
import unittest

from jcc import watch


def answer(*titles):
    """What the lookup sends back: (kind, title, year, [(how, service), ...]) for each title, likeliest first."""
    return {"data": {"popularTitles": {"edges": [
        {"node": {"objectType": kind, "content": {"title": title, "originalReleaseYear": year},
                  "offers": [{"monetizationType": how, "package": {"clearName": service}} for how, service in offers]}}
        for kind, title, year, offers in titles]}}}


INCEPTION = ("MOVIE", "Inception", 2010, [("BUY", "Apple TV Store"), ("FLATRATE", "Netflix"), ("FLATRATE", "Amazon Prime Video"),
                                          ("FLATRATE", "Amazon Prime Video with Ads"), ("FLATRATE", "JioHotstar"), ("RENT", "Amazon Video"), ("RENT", "Apple TV Store")])


class TestWhereToWatch(unittest.TestCase):
    def setUp(self):
        watch._kept.clear()
        self.asked = []

    def ask(self, reply):
        def asked(title, where):
            self.asked.append((title, where))
            if isinstance(reply, BaseException):
                raise reply
            return reply
        return asked

    def test_where_a_title_is_streaming_and_which_of_those_jarvis_can_start_itself(self):
        found = watch.lookup("inception", "IN", self.ask(answer(INCEPTION)))
        self.assertEqual((found["title"], found["year"], found["kind"], found["country"]), ("Inception", 2010, "film", "IN"))
        self.assertEqual(found["stream"], ["Netflix", "Amazon Prime Video", "Amazon Prime Video with Ads", "JioHotstar"])
        self.assertEqual((found["rent"], found["buy"]), (["Amazon Video", "Apple TV Store"], ["Apple TV Store"]))
        self.assertEqual(watch.services(found), ["netflix", "prime video", "hotstar"])
        self.assertEqual(watch.describe(found), '"Inception" (2010 film) is streaming on Netflix, Amazon Prime Video, JioHotstar.')
        self.assertEqual(self.asked, [("inception", "IN")], "only the title and the country are sent")

    def test_a_series_and_a_title_that_can_only_be_rented(self):
        series = watch.lookup("Money Heist", "IN", self.ask(answer(("SHOW", "Money Heist", 2017, [("FLATRATE", "Netflix")]))))
        self.assertEqual((series["kind"], watch.services(series)), ("series", ["netflix"]))
        rented = watch.lookup("Some Film", "IN", self.ask(answer(("MOVIE", "Some Film", 2021, [("RENT", "Apple TV Store"), ("BUY", "Apple TV Store")]))))
        self.assertEqual(watch.services(rented), [])
        self.assertEqual(watch.describe(rented), '"Some Film" (2021 film) is not on a streaming service in IN; it can be rented or bought on Apple TV Store.')
        nowhere = watch.lookup("Old Film", "IN", self.ask(answer(("MOVIE", "Old Film", 1950, []))))
        self.assertIn("not available to stream, rent or buy", watch.describe(nowhere))
        elsewhere = watch.lookup("Anime", "IN", self.ask(answer(("SHOW", "Anime", 2020, [("FLATRATE", "Crunchyroll"), ("ADS", "YouTube")]))))
        self.assertEqual(watch.services(elsewhere), ["youtube"], "a service JARVIS has no way into is named, not started")

    def test_the_title_with_exactly_this_name_wins_and_a_look_alike_is_nothing(self):
        reply = answer(("MOVIE", "The Dark Knight Rises", 2012, [("FLATRATE", "Netflix")]), ("MOVIE", "The Dark Knight", 2008, [("FLATRATE", "JioHotstar")]))
        self.assertEqual(watch.lookup("the dark knight", "IN", self.ask(reply))["title"], "The Dark Knight")
        self.assertEqual(watch.lookup("dark knight", "IN", self.ask(reply))["title"], "The Dark Knight Rises", "no exact name: the likeliest that is about these words")
        self.assertEqual(watch.lookup("Avengers Endgame", "IN", self.ask(answer(("MOVIE", "Avengers: Endgame", 2019, []))))["title"], "Avengers: Endgame")
        # The lookup also offers things that merely sound alike. That is not the title that was asked for.
        self.assertIsNone(watch.lookup("zzqq no such film xx", "IN", self.ask(answer(("SHOW", "Watari-kun no xx ga Hokai Sunzen", 2025, [("FLATRATE", "Crunchyroll")])))))
        self.assertEqual(watch.describe(None), "")
        self.assertEqual(watch.services(None), [])

    def test_no_answer_is_nothing_known_and_is_asked_again_next_time(self):
        self.assertIsNone(watch.lookup("Inception", "IN", self.ask(OSError("offline"))))
        self.assertIsNone(watch.lookup("Inception", "IN", self.ask({"errors": ["changed"]})), "an answer in another shape than expected")
        self.assertEqual(watch.lookup("Inception", "IN", self.ask(answer(INCEPTION)))["title"], "Inception")
        self.assertEqual(len(self.asked), 3)
        self.assertIsNone(watch.lookup("", "IN", self.ask(answer(INCEPTION))))

    def test_an_answer_is_kept_for_an_hour(self):
        watch.lookup("Inception", "IN", self.ask(answer(INCEPTION)))
        again = watch.lookup(" inception ", "in", self.ask(OSError("not asked")))
        self.assertEqual(again["title"], "Inception")
        self.assertEqual(len(self.asked), 1)
        watch.lookup("Inception", "US", self.ask(answer(INCEPTION)))
        self.assertEqual(len(self.asked), 2, "another country is another question")

    def test_the_country_is_two_letters(self):
        self.assertRegex(watch.country(), r"^[A-Z]{2}$")


if __name__ == "__main__":
    unittest.main()
