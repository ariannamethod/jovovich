#!/usr/bin/env python3
"""Plot the complete frozen layer survey from its verified final TSV table.

Creates standalone SVG and PNG files. No interpolation, smoothing or layer
selection is performed. The caller validates the final native summary first.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

COLUMNS = ['view', 'correct', 'correct_concern', 'correct_clean', 'complete_pairs',
           'shuffled_correct', 'shuffled_complete_pairs']
VIEW_NAMES = [f'{boundary}-layer-{layer:02d}' for boundary in ('header', 'prefix')
              for layer in range(24)] + ['prefix-final-mlp-z', 'nuisance']


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_table(path):
    with path.open(newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        require(reader.fieldnames == COLUMNS, 'Unexpected TSV columns')
        raw_rows = list(reader)
    require([row['view'] for row in raw_rows] == VIEW_NAMES,
            'Expected all 50 views in the frozen table order')
    rows = {}
    for raw in raw_rows:
        require(set(raw) == set(COLUMNS) and all(raw[key] is not None for key in COLUMNS),
                'Incomplete TSV row')
        values = {key: int(raw[key]) for key in COLUMNS[1:]}
        require(0 <= values['correct_concern'] <= 26 and 0 <= values['correct_clean'] <= 26,
                'Class counts exceed the cohort')
        require(values['correct'] == values['correct_concern'] + values['correct_clean'],
                'Observed row counts disagree')
        require(max(0, values['correct'] - 26) <= values['complete_pairs'] <=
                min(values['correct_concern'], values['correct_clean']),
                'Observed pair counts disagree with row counts')
        require(0 <= values['shuffled_correct'] <= 52 and
                max(0, values['shuffled_correct'] - 26) <= values['shuffled_complete_pairs'] <=
                values['shuffled_correct'] // 2,
                'Flipped-label pair counts disagree with row counts')
        rows[raw['view']] = values
    return rows


def plot(table, out_prefix):
    rows = read_table(table)
    paths = {'svg': Path(str(out_prefix) + '.svg'), 'png': Path(str(out_prefix) + '.png')}
    require(all(not path.exists() for path in paths.values()), 'Figure outputs must be new files')
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt

    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11,
                         'axes.titlesize': 12, 'axes.labelsize': 11,
                         'axes.edgecolor': '#B3BAC3', 'axes.linewidth': .7,
                         'xtick.color': '#46515F', 'ytick.color': '#46515F',
                         'text.color': '#26313E', 'axes.labelcolor': '#26313E',
                         'svg.fonttype': 'none', 'svg.hashsalt': 'jovovich-layer-survey-v1'})
    fig, axes = plt.subplots(2, 1, figsize=(10.8, 8.0), sharex=True)
    fig.patch.set_facecolor('white')
    fig.subplots_adjust(left=.09, right=.97, bottom=.20, top=.76, hspace=.24)
    fig.text(.09, .965, 'Qwen 0.5B · frozen residual readout',
             fontsize=18, fontweight='bold', ha='left', va='top')
    fig.text(.09, .923,
             'Development cohort · leave one of 20 families out · ridge λ = 0.01',
             fontsize=11.5, color='#46515F', ha='left', va='top')
    fig.text(.09, .890,
             '52 reviews · 26 matched concern/clean pairs · all 24 transformer blocks',
             fontsize=10.5, color='#46515F', ha='left', va='top')

    layers = list(range(1, 25))
    colors = {'header': '#0072B2', 'prefix': '#D55E00'}
    labels = {'header': 'Assistant header end', 'prefix': 'Shared-prefix end'}
    settings = [('correct', 'shuffled_correct', 52, 'Correct reviews / 52', [0, 13, 26, 39, 52]),
                ('complete_pairs', 'shuffled_complete_pairs', 26, 'Complete pairs / 26', [0, 6, 13, 20, 26])]
    for axis, (metric, shuffled, maximum, label, ticks) in zip(axes, settings):
        axis.set_facecolor('white')
        for boundary in ('header', 'prefix'):
            values = [rows[f'{boundary}-layer-{index:02d}'][metric] for index in range(24)]
            controls = [rows[f'{boundary}-layer-{index:02d}'][shuffled] for index in range(24)]
            axis.plot(layers, values, color=colors[boundary], linewidth=1.9,
                      marker='o', markersize=3.2, label=labels[boundary], zorder=3)
            axis.plot(layers, controls, color=colors[boundary], linewidth=1.35,
                      linestyle=(0, (1.0, 2.0)), alpha=.85,
                      label=labels[boundary] + ' · fixed-label flip', zorder=2)
        axis.axhline(rows['nuisance'][metric], color='#747D88', linewidth=1.35,
                     linestyle=(0, (5, 3)), label='Lexical/count baseline', zorder=1)
        axis.set_ylim(-.7, maximum + .7)
        axis.set_yticks(ticks)
        axis.set_ylabel(label)
        axis.grid(axis='y', color='#E4E8ED', linewidth=.7)
        axis.spines['top'].set_visible(False)
        axis.spines['right'].set_visible(False)
        axis.tick_params(length=3, width=.7)
    axes[1].set_xlim(.7, 24.3)
    axes[1].set_xticks([1, 4, 8, 12, 16, 20, 24])
    axes[1].set_xlabel('Transformer block (1–24; native indices 0–23)')
    handles, legend_labels = axes[0].get_legend_handles_labels()
    order = [0, 2, 1, 3, 4]
    fig.legend([handles[i] for i in order], [legend_labels[i] for i in order],
               loc='upper left', bbox_to_anchor=(.082, .856), ncol=2,
               fontsize=9.5, frameon=False, columnspacing=2.0,
               handlelength=3.0, labelspacing=.55)
    anchor = rows['prefix-final-mlp-z']
    fig.text(.09, .115,
             f"Fresh pre-final-MLP z anchor at shared prefix: {anchor['correct']}/52 reviews; "
             f"{anchor['complete_pairs']}/26 complete pairs.",
             fontsize=10.2, ha='left', va='top')
    fig.text(.09, .085,
             f"Anchor fixed-label flip: {anchor['shuffled_correct']}/52 reviews; "
             f"{anchor['shuffled_complete_pairs']}/26 pairs. Dotted lines use one fixed family-label flip.",
             fontsize=9.5, color='#46515F', ha='left', va='top')
    fig.text(.09, .049,
             'Solid lines: observed labels. Each plotted point retains its original family-held-out prediction counts.',
             fontsize=9.0, color='#66717E', ha='left', va='top')
    fig.savefig(paths['svg'], facecolor='white', metadata={'Date': None,
                'Title': 'JOVOVICH frozen Qwen layer survey',
                'Description': 'Development family-held-out counts at all 24 post-block residuals and two token boundaries.'})
    paths['svg'].write_text('\n'.join(line.rstrip() for line in
                                    paths['svg'].read_text().splitlines()) + '\n')
    fig.savefig(paths['png'], facecolor='white', dpi=180,
                metadata={'Title': 'JOVOVICH frozen Qwen layer survey'})
    plt.close(fig)
    print(json.dumps({'table': str(table), 'table_sha256': hashlib.sha256(table.read_bytes()).hexdigest(),
                      'views_plotted': 48, 'state_anchor': 'prefix-final-mlp-z',
                      'outputs': {kind: str(path) for kind, path in paths.items()}}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--table', type=Path, required=True)
    parser.add_argument('--out-prefix', type=Path, required=True)
    args = parser.parse_args()
    plot(args.table.resolve(), args.out_prefix.resolve())
