import sqlite3, unittest
from bro_runtime.final_delivery import (
    Assurance, CapabilityReceipt, DisasterRecoveryReceipt, DurableTruthCustody,
    FinalDeliveryRejected, IntelligentInteractionRuntime, ProductionServiceControl,
)


class FinalDeliveryTests(unittest.TestCase):
    def _interaction(self):
        return IntelligentInteractionRuntime(
            interpreter=lambda text: {
                'scope': ('update external business record',),
                'constraints': ('preserve authority boundary',),
                'success_conditions': ('external state reads back independently',),
                'material': True,
            },
            planner=lambda intent: 'specialist:crm',
            executor=lambda intent, specialist: {'provider_ref':'provider:crm-write','effect_ref':'effect:42'},
            readback=lambda intent, effect: {
                'provider_ref':'provider:crm-readback','readback_ref':'readback:42',
                'evidence_ref':'evidence:42','assurance':'external_system'},
            model_ref='model:production-router-v1',
        )

    def test_material_interaction_requires_confirmed_scope_and_external_readback(self):
        runtime=self._interaction(); intent=runtime.interpret('Update the customer record and verify it.')
        with self.assertRaisesRegex(FinalDeliveryRejected,'explicit confirmation'):
            runtime.execute(intent.request_id)
        runtime.confirm_scope(intent.request_id,confirmed_by='user:gev',scope_digest=runtime.scope_digest(intent.request_id))
        receipt=runtime.execute(intent.request_id)
        self.assertEqual(receipt.assurance,Assurance.EXTERNAL_SYSTEM)
        self.assertNotEqual(receipt.provider_ref,receipt.readback_provider_ref)

    def test_repository_only_or_self_attested_readback_fails_closed(self):
        runtime=IntelligentInteractionRuntime(
            interpreter=lambda text:{'scope':('x',),'success_conditions':('y',),'material':False},
            planner=lambda intent:'specialist:x',
            executor=lambda intent,s:{'provider_ref':'provider:x','effect_ref':'effect:x'},
            readback=lambda intent,e:{'provider_ref':'provider:x','readback_ref':'effect:x','evidence_ref':'e:x','assurance':'repository'},
            model_ref='model:production-router-v1')
        intent=runtime.interpret('do x')
        with self.assertRaises(FinalDeliveryRejected): runtime.execute(intent.request_id)

    def test_production_identity_vault_human_channel_and_fencing_are_required(self):
        c=sqlite3.connect(':memory:'); control=ProductionServiceControl(c)
        with self.assertRaisesRegex(FinalDeliveryRejected,'external backend'):
            control.register_instance(service_id='bro',instance_id='a',identity_subject='iam:bro-a',vault_backend='test',approval_channel='https://approval.example')
        control.register_instance(service_id='bro',instance_id='a',identity_subject='iam:bro-a',vault_backend='vault://prod',approval_channel='https://approval.example')
        control.register_instance(service_id='bro',instance_id='b',identity_subject='iam:bro-b',vault_backend='vault://prod',approval_channel='https://approval.example')
        a=control.claim_primary(service_id='bro',instance_id='a',now_epoch=100,lease_seconds=10)
        with self.assertRaisesRegex(FinalDeliveryRejected,'live primary lease'):
            control.claim_primary(service_id='bro',instance_id='b',now_epoch=105,lease_seconds=10)
        b=control.claim_primary(service_id='bro',instance_id='b',now_epoch=111,lease_seconds=10)
        with self.assertRaisesRegex(FinalDeliveryRejected,'stale production fencing token'):
            control.assert_fence(a,now_epoch=111)
        control.assert_fence(b,now_epoch=112)

    def test_truth_custody_is_remote_append_only_chain(self):
        c=sqlite3.connect(':memory:'); custody=DurableTruthCustody(c)
        with self.assertRaisesRegex(FinalDeliveryRejected,'remote'):
            custody.record(object_ref='e:1',payload_digest='a'*64,custody_uri='/tmp/evidence',assurance=Assurance.EXTERNAL_SYSTEM)
        first=custody.record(object_ref='e:1',payload_digest='a'*64,custody_uri='s3://bro-prod/e/1',assurance=Assurance.EXTERNAL_SYSTEM)
        second=custody.record(object_ref='e:2',payload_digest='b'*64,custody_uri='s3://bro-prod/e/2',assurance=Assurance.PRODUCTION)
        self.assertEqual(second.previous_digest,first.digest); self.assertTrue(custody.verify_chain())

    def test_production_graduation_requires_all_three_blocks_and_real_dr(self):
        c=sqlite3.connect(':memory:'); control=ProductionServiceControl(c); custody=DurableTruthCustody(c)
        control.register_instance(service_id='bro',instance_id='a',identity_subject='iam:bro-a',vault_backend='vault://prod',approval_channel='https://approval.example')
        lease=control.claim_primary(service_id='bro',instance_id='a',now_epoch=100,lease_seconds=30)
        custody.record(object_ref='evidence:external',payload_digest='a'*64,custody_uri='s3://bro-prod/evidence/external',assurance=Assurance.PRODUCTION)
        interaction=CapabilityReceipt('request:1','specialist:crm','provider:w','effect:1','readback:1','provider:r','evidence:1',Assurance.EXTERNAL_SYSTEM)
        with self.assertRaisesRegex(FinalDeliveryRejected,'production assurance'):
            custody.graduate(interaction=interaction,production_lease=lease,service_control=control,now_epoch=110,dr=DisasterRecoveryReceipt('backup:1','s3://bro-prod/backups/1','restore:1',Assurance.EXTERNAL_SYSTEM),production_acceptance_ref='acceptance:1',unresolved_contradictions=0)
        verdict=custody.graduate(interaction=interaction,production_lease=lease,service_control=control,now_epoch=110,dr=DisasterRecoveryReceipt('backup:1','s3://bro-prod/backups/1','restore:1',Assurance.PRODUCTION),production_acceptance_ref='acceptance:1',unresolved_contradictions=0)
        self.assertEqual(verdict,'PRODUCTION_GRADUATED:acceptance:1')

    def test_unresolved_contradiction_blocks_graduation(self):
        c=sqlite3.connect(':memory:'); control=ProductionServiceControl(c); custody=DurableTruthCustody(c)
        control.register_instance(service_id='bro',instance_id='a',identity_subject='iam:bro-a',vault_backend='vault://prod',approval_channel='https://approval.example')
        lease=control.claim_primary(service_id='bro',instance_id='a',now_epoch=1,lease_seconds=30)
        custody.record(object_ref='e:1',payload_digest='a'*64,custody_uri='https://custody.example/e/1',assurance=Assurance.PRODUCTION)
        interaction=CapabilityReceipt('r','s','p:w','e','rb','p:r','ev',Assurance.EXTERNAL_SYSTEM)
        with self.assertRaisesRegex(FinalDeliveryRejected,'zero unresolved'):
            custody.graduate(interaction=interaction,production_lease=lease,service_control=control,now_epoch=2,dr=DisasterRecoveryReceipt('b','s3://bro-prod/b','restore:1',Assurance.PRODUCTION),production_acceptance_ref='acceptance:prod',unresolved_contradictions=1)


if __name__=='__main__': unittest.main()
