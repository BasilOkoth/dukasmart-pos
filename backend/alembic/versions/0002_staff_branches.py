"""Staff branch assignments; preserve existing business data."""
from alembic import op
import sqlalchemy as sa
revision='0002'
down_revision='0001'
branch_labels=None
depends_on=None
def upgrade():
    op.create_table('staff_branches',sa.Column('id',sa.String(36),primary_key=True),sa.Column('membership_id',sa.String(36),sa.ForeignKey('memberships.id',ondelete='CASCADE'),nullable=False),sa.Column('branch_id',sa.String(36),sa.ForeignKey('branches.id',ondelete='CASCADE'),nullable=False),sa.UniqueConstraint('membership_id','branch_id'))
    op.create_index('ix_staff_branches_membership_id','staff_branches',['membership_id'])
    op.create_index('ix_staff_branches_branch_id','staff_branches',['branch_id'])
def downgrade():
    op.drop_table('staff_branches')
