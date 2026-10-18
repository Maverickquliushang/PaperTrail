import unittest
from scripts.update_catalog import eligible
from scripts.public_records import parse_dblp, parse_public_submissions
from datetime import date


class PublicRecordTests(unittest.TestCase):
    def test_dblp_year_is_not_fabricated_as_day(self):
        def hit(key, venue='ICML', year='2018', kind='Conference and Workshop Papers'):
            return {'info':{'key':key,'venue':venue,'year':year,'type':kind,'title':'Study',
                            'authors':{'author':{'text':'Author'}},'ee':'https://doi.org/10.1234/example'}}
        payload={'result':{'hits':{'@total':'5','hit':[
            hit('conf/icml/paper'),hit('conf/icml/workshop','ICML Workshop'),
            hit('conf/icml/book',kind='Editorship'),hit('conf/other/paper'),hit('conf/icml/future',year='2099')]}}}
        records,total=parse_dblp(payload,'ICML','2026-10-18',2026)
        self.assertEqual(total,5)
        self.assertEqual(len(records),1)
        self.assertEqual(records[0].publication_year,2018)
        self.assertIsNone(records[0].filter_date)
        self.assertEqual(records[0].doi,'10.1234/example')
        self.assertTrue(eligible(records[0],date(2026,10,18)))

    def test_public_submission_states_use_explicit_venue_mapping(self):
        venue='ICLR.cc/2027/Conference'
        invitation=venue+'/-/Submission'
        def note(identifier, state, **extra):
            return {'id':identifier,'invitations':[invitation],'readers':['everyone'],
                    'cdate':1790000000000,'content':{'title':{'value':'Study'},'venueid':{'value':state}},**extra}
        notes=[note('a',venue),note('b',venue+'/Submission'),note('c',venue+'/Withdrawn'),
               note('d','unrecognized'),note('private',venue,readers=['editors']),note('reply',venue,replyto='a')]
        result=parse_public_submissions({'notes':notes},'ICLR',venue,invitation,
            {venue+'/Submission':'under_review',venue+'/Withdrawn':'withdrawn'},'2026-10-18')
        self.assertEqual([r.review_status for r in result],['accepted','under_review','withdrawn','unknown'])
        self.assertIsNone(result[0].publication_date)  # Missing acceptance date stays missing.
        self.assertIsNotNone(result[1].publication_date)
