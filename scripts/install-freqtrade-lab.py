"""Stage the native dry-run catalog without changing engine config or orders."""
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]

def install():
    target=(ROOT.parent/'freqtrade/user_data/strategies').resolve()
    intended=(ROOT.parent/'freqtrade').resolve()
    if not target.is_relative_to(intended) or not target.is_dir():
        raise ValueError('Expected sibling Freqtrade strategy directory')
    package=target/'niblit_lab'
    package.mkdir(exist_ok=True)
    (package/'__init__.py').write_text('',encoding='utf-8')
    shutil.copyfile(ROOT/'modules/demo_strategy.py',package/'demo_strategy.py')
    exits=(ROOT/'modules/position_exit_policy.py').read_text(encoding='utf-8')
    (package/'position_exit_policy.py').write_text(exits.replace('from modules.demo_strategy import','from .demo_strategy import'),encoding='utf-8')
    manager=(ROOT/'modules/strategy_manager.py').read_text(encoding='utf-8')
    (package/'strategy_manager.py').write_text(manager.replace('from modules.demo_strategy import','from .demo_strategy import'),encoding='utf-8')
    shutil.copyfile(ROOT/'modules/freqtrade_chart_adapter.py',target/'niblit_chart_plot.py')
    shutil.copyfile(ROOT/'deploy/freqtrade-lab/NiblitLabManager.py',target/'NiblitLabManager.py')
    shutil.copyfile(ROOT/'modules/freqtrade_core_claim.py',package/'core_claim.py')
    shutil.copyfile(ROOT/'deploy/freqtrade-lab/NiblitCoreManaged.py',target/'NiblitCoreManaged.py')
    shutil.copyfile(ROOT/'deploy/freqtrade-lab/NiblitMicroDemo.py',target/'NiblitMicroDemo.py')
    print('Staged seven dry-run strategy classes. Running config and trades were not changed.')

if __name__=='__main__': install()
