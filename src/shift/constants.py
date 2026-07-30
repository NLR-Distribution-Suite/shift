from gdm.distribution.components import (
    DistributionTransformer,
    DistributionBranchBase,
    MatrixImpedanceBranch,
    SequenceImpedanceBranch,
    GeometryBranch,
    MatrixImpedanceFuse,
    MatrixImpedanceSwitch,
    MatrixImpedanceRecloser,
)
from gdm.distribution.equipment import (
    SequenceImpedanceBranchEquipment,
    MatrixImpedanceBranchEquipment,
    GeometryBranchEquipment,
    MatrixImpedanceFuseEquipment,
    MatrixImpedanceRecloserEquipment,
    MatrixImpedanceSwitchEquipment,
    DistributionTransformerEquipment,
)

EQUIPMENT_TO_CLASS_TYPE = {
    DistributionBranchBase: MatrixImpedanceBranchEquipment,
    MatrixImpedanceBranch: MatrixImpedanceBranchEquipment,
    MatrixImpedanceFuse: MatrixImpedanceFuseEquipment,
    MatrixImpedanceRecloser: MatrixImpedanceRecloserEquipment,
    MatrixImpedanceSwitch: MatrixImpedanceSwitchEquipment,
    SequenceImpedanceBranch: SequenceImpedanceBranchEquipment,
    GeometryBranch: GeometryBranchEquipment,
    DistributionTransformer: DistributionTransformerEquipment,
}
