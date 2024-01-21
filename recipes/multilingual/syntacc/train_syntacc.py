import os

import torch
from trainer import Trainer, TrainerArgs

from TTS.bin.compute_embeddings import compute_embeddings
from TTS.bin.resample import resample_files
from TTS.config.shared_configs import BaseDatasetConfig
from TTS.tts.configs.vits_config import VitsConfig
from TTS.tts.datasets import load_tts_samples
from TTS.tts.models.vits import CharactersConfig, Vits, VitsArgs, VitsAudioConfig, VitsDataset
from TTS.utils.downloaders import download_libri_tts
from torch.utils.data import DataLoader
from TTS.utils.samplers import PerfectBatchSampler
torch.set_num_threads(24)

# pylint: disable=W0105
"""
    This recipe replicates the first experiment proposed in the CML-TTS paper (https://arxiv.org/abs/2306.10097). It uses the YourTTS model.
    YourTTS model is based on the VITS model however it uses external speaker embeddings extracted from a pre-trained speaker encoder and has small architecture changes.
"""
CURRENT_PATH = os.path.dirname(os.path.abspath(__file__))

# Name of the run for the Trainer
RUN_NAME = "YourTTS-CML-TTS"

# Path where you want to save the models outputs (configs, checkpoints and tensorboard logs)
OUT_PATH = os.path.dirname(os.path.abspath(__file__))  # "/raid/coqui/Checkpoints/original-YourTTS/"

# If you want to do transfer learning and speedup your training you can set here the path to the CML-TTS available checkpoint that cam be downloaded here:  https://drive.google.com/u/2/uc?id=1yDCSJ1pFZQTHhL09GMbOrdjcPULApa0p
RESTORE_PATH = None # "/raid/edresson/CML_YourTTS/checkpoints_yourtts_cml_tts_dataset/best_model.pth"  # Download the checkpoint here:  https://drive.google.com/u/2/uc?id=1yDCSJ1pFZQTHhL09GMbOrdjcPULApa0p

# This paramter is useful to debug, it skips the training epochs and just do the evaluation  and produce the test sentences
SKIP_TRAIN_EPOCH = False

# Set here the batch size to be used in training and evaluation
BATCH_SIZE = 6

# Training Sampling rate and the target sampling rate for resampling the downloaded dataset (Note: If you change this you might need to redownload the dataset !!)
# Note: If you add new datasets, please make sure that the dataset sampling rate and this parameter are matching, otherwise resample your audios
SAMPLE_RATE = 16000

# Max audio length in seconds to be used in training (every audio bigger than it will be ignored)
MAX_AUDIO_LEN_IN_SECONDS = float("inf")

# Define here the datasets config
brpb_train_config = BaseDatasetConfig(
    formatter="coqui",
    dataset_name="mupe",
    meta_file_train="metadata_coqui_brpb.csv",
    path="/PROJ/data/metadata/v-180124/",
    language="brpb"
)

brba_train_config = BaseDatasetConfig(
    formatter="coqui",
    dataset_name="mupe",
    meta_file_train="metadata_coqui_brba.csv",
    path="/PROJ/data/metadata/v-180124/",
    language="brba"
)

brportugal_train_config = BaseDatasetConfig(
    formatter="coqui",
    dataset_name="mupe",
    meta_file_train="metadata_coqui_brportugal.csv",
    path="/PROJ/data/metadata/v-180124/",
    language="brportugal"
)

brsp_train_config = BaseDatasetConfig(
    formatter="coqui",
    dataset_name="mupe",
    meta_file_train="metadata_coqui_brsp.csv",
    path="/PROJ/data/metadata/v-180124/",
    language="brsp"
)

brpe_train_config = BaseDatasetConfig(
    formatter="coqui",
    dataset_name="mupe",
    meta_file_train="metadata_coqui_brpe.csv",
    path="/PROJ/data/metadata/v-180124/",
    language="brpe"
)

brmg_train_config = BaseDatasetConfig(
    formatter="coqui",
    dataset_name="mupe",
    meta_file_train="metadata_coqui_brmg.csv",
    path="/PROJ/data/metadata/v-180124/",
    language="brmg"
)

brrj_train_config = BaseDatasetConfig(
    formatter="coqui",
    dataset_name="mupe",
    meta_file_train="metadata_coqui_brrj.csv",
    path="/PROJ/data/metadata/v-180124/",
    language="brrj"
)

brce_train_config = BaseDatasetConfig(
    formatter="coqui",
    dataset_name="mupe",
    meta_file_train="metadata_coqui_brce.csv",
    path="/PROJ/data/metadata/v-180124/",
    language="brce"
)

brrs_train_config = BaseDatasetConfig(
    formatter="coqui",
    dataset_name="mupe",
    meta_file_train="metadata_coqui_brrs.csv",
    path="/PROJ/data/metadata/v-180124/",
    language="brrs"
)

bralemanha_train_config = BaseDatasetConfig(
    formatter="coqui",
    dataset_name="mupe",
    meta_file_train="metadata_coqui_bralemanha.csv",
    path="/PROJ/data/metadata/v-180124/",
    language="bralemanha"
)

brgo_train_config = BaseDatasetConfig(
    formatter="coqui",
    dataset_name="mupe",
    meta_file_train="metadata_coqui_brgo.csv",
    path="/PROJ/data/metadata/v-180124/",
    language="brgo"
)

bral_train_config = BaseDatasetConfig(
    formatter="coqui",
    dataset_name="mupe",
    meta_file_train="metadata_coqui_bral.csv",
    path="/PROJ/data/metadata/v-180124/",
    language="bral"
)

brpr_train_config = BaseDatasetConfig(
    formatter="coqui",
    dataset_name="mupe",
    meta_file_train="metadata_coqui_brpr.csv",
    path="/PROJ/data/metadata/v-180124/",
    language="brpr"
)

bres_train_config = BaseDatasetConfig(
    formatter="coqui",
    dataset_name="mupe",
    meta_file_train="metadata_coqui_bres.csv",
    path="/PROJ/data/metadata/v-180124/",
    language="bres"
)

brpi_train_config = BaseDatasetConfig(
    formatter="coqui",
    dataset_name="mupe",
    meta_file_train="metadata_coqui_brpi.csv",
    path="/PROJ/data/metadata/v-180124/",
    language="brpi"
)

DATASETS_CONFIG_LIST = [brpb_train_config,brba_train_config,brportugal_train_config,brsp_train_config,brpe_train_config,brmg_train_config,brrj_train_config,brce_train_config,brrs_train_config,bralemanha_train_config,brgo_train_config,bral_train_config,brpr_train_config,bres_train_config,brpi_train_config]


### Extract speaker embeddings
SPEAKER_ENCODER_CHECKPOINT_PATH = (
    "https://github.com/coqui-ai/TTS/releases/download/speaker_encoder_model/model_se.pth.tar"
)
SPEAKER_ENCODER_CONFIG_PATH = "https://github.com/coqui-ai/TTS/releases/download/speaker_encoder_model/config_se.json"

D_VECTOR_FILES = []  # List of speaker embeddings/d-vectors to be used during the training

# Iterates all the dataset configs checking if the speakers embeddings are already computated, if not compute it
for dataset_conf in DATASETS_CONFIG_LIST:
    # Check if the embeddings weren't already computed, if not compute it
    embeddings_file = os.path.join(dataset_conf.path, "H_ASP_speaker_embeddings.pth")
    if not os.path.isfile(embeddings_file):
        print(f">>> Computing the speaker embeddings for the {dataset_conf.dataset_name} dataset")
        compute_embeddings(
            SPEAKER_ENCODER_CHECKPOINT_PATH,
            SPEAKER_ENCODER_CONFIG_PATH,
            embeddings_file,
            old_speakers_file=None,
            config_dataset_path=None,
            formatter_name=dataset_conf.formatter,
            dataset_name=dataset_conf.dataset_name,
            dataset_path=dataset_conf.path,
            meta_file_train=dataset_conf.meta_file_train,
            meta_file_val=dataset_conf.meta_file_val,
            disable_cuda=False,
            no_eval=False,
        )
    D_VECTOR_FILES.append(embeddings_file)


# Audio config used in training.
audio_config = VitsAudioConfig(
    sample_rate=SAMPLE_RATE,
    hop_length=256,
    win_length=1024,
    fft_size=1024,
    mel_fmin=0.0,
    mel_fmax=None,
    num_mels=80,
)

# Init VITSArgs setting the arguments that are needed for the YourTTS model
model_args = VitsArgs(
    spec_segment_size=62,
    hidden_channels=192,
    hidden_channels_ffn_text_encoder=768,
    num_heads_text_encoder=2,
    num_layers_text_encoder=10,
    kernel_size_text_encoder=3,
    dropout_p_text_encoder=0.1,
    d_vector_file=D_VECTOR_FILES,
    use_d_vector_file=True,
    d_vector_dim=512,
    speaker_encoder_model_path=SPEAKER_ENCODER_CHECKPOINT_PATH,
    speaker_encoder_config_path=SPEAKER_ENCODER_CONFIG_PATH,
    resblock_type_decoder="2",  # In the paper, we accidentally trained the YourTTS using ResNet blocks type 2, if you like you can use the ResNet blocks type 1 like the VITS model
    # Useful parameters to enable the Speaker Consistency Loss (SCL) described in the paper
    use_speaker_encoder_as_loss=False,
    # Useful parameters to enable multilingual training
    use_language_embedding=False,
    embedded_language_dim=4,
    use_adaptive_weight_text_encoder=True,
    use_perfect_class_batch_sampler=True,
    perfect_class_batch_sampler_key="language"
)

# General training config, here you can change the batch size and others useful parameters
config = VitsConfig(
    output_path=OUT_PATH,
    model_args=model_args,
    run_name=RUN_NAME,
    project_name="SYNTACC",
    run_description="""
            - YourTTS with SYNTACC text encoder
        """,
    dashboard_logger="tensorboard",
    logger_uri=None,
    audio=audio_config,
    batch_size=BATCH_SIZE,
    batch_group_size=48,
    eval_batch_size=BATCH_SIZE,
    num_loader_workers=8,
    eval_split_max_size=256,
    print_step=50,
    plot_step=100,
    log_model_step=1000,
    save_step=5000,
    save_n_checkpoints=2,
    save_checkpoints=True,
    # target_loss="loss_1",
    print_eval=False,
    use_phonemes=False,
    phonemizer="espeak",
    phoneme_language="en",
    compute_input_seq_cache=True,
    add_blank=True,
    text_cleaner="multilingual_cleaners",
    characters=CharactersConfig(
        characters_class="TTS.tts.models.vits.VitsCharacters",
        pad="_",
        eos="&",
        bos="*",
        blank=None,
        characters="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz\u00a1\u00a3\u00b7\u00b8\u00c0\u00c1\u00c2\u00c3\u00c4\u00c5\u00c7\u00c8\u00c9\u00ca\u00cb\u00cc\u00cd\u00ce\u00cf\u00d1\u00d2\u00d3\u00d4\u00d5\u00d6\u00d9\u00da\u00db\u00dc\u00df\u00e0\u00e1\u00e2\u00e3\u00e4\u00e5\u00e7\u00e8\u00e9\u00ea\u00eb\u00ec\u00ed\u00ee\u00ef\u00f1\u00f2\u00f3\u00f4\u00f5\u00f6\u00f9\u00fa\u00fb\u00fc\u0101\u0104\u0105\u0106\u0107\u010b\u0119\u0141\u0142\u0143\u0144\u0152\u0153\u015a\u015b\u0161\u0178\u0179\u017a\u017b\u017c\u020e\u04e7\u05c2\u1b20",
        punctuations="\u2014!'(),-.:;?\u00bf ",
        phonemes="iy\u0268\u0289\u026fu\u026a\u028f\u028ae\u00f8\u0258\u0259\u0275\u0264o\u025b\u0153\u025c\u025e\u028c\u0254\u00e6\u0250a\u0276\u0251\u0252\u1d7b\u0298\u0253\u01c0\u0257\u01c3\u0284\u01c2\u0260\u01c1\u029bpbtd\u0288\u0256c\u025fk\u0261q\u0262\u0294\u0274\u014b\u0272\u0273n\u0271m\u0299r\u0280\u2c71\u027e\u027d\u0278\u03b2fv\u03b8\u00f0sz\u0283\u0292\u0282\u0290\u00e7\u029dx\u0263\u03c7\u0281\u0127\u0295h\u0266\u026c\u026e\u028b\u0279\u027bj\u0270l\u026d\u028e\u029f\u02c8\u02cc\u02d0\u02d1\u028dw\u0265\u029c\u02a2\u02a1\u0255\u0291\u027a\u0267\u025a\u02de\u026b'\u0303' ",
        is_unique=True,
        is_sorted=True,
    ),
    phoneme_cache_path=None,
    precompute_num_workers=12,
    start_by_longest=True,
    datasets=DATASETS_CONFIG_LIST,
    cudnn_benchmark=False,
    max_audio_len=SAMPLE_RATE * MAX_AUDIO_LEN_IN_SECONDS,
    mixed_precision=False,
    test_sentences=[
        #GUSTAVO: apenas pessoas do treino
        ["Voc\u00ea ter\u00e1 a vista do topo da montanha que voc\u00ea escalar.", "EDILEINE_FONSECA", None, "brsp"],
        ["Quem semeia ventos, colhe tempestades.", "JOSE_PAULO_DE_ARAUJO", None, "brpb"],
        ["O olho do dono \u00e9 que engorda o gado.", "VITOR_RAFAEL_OLIVEIRA_ALVES", None, "brba"],
        ["\u00c1gua mole em pedra dura, tanto bate at\u00e9 que fura.", "MARIA_AURORA_FELIX", None, "brportugal"],
        ["Quem espera sempre alcan\u00e7a.", "ANTONIO_DE_AMORIM_COSTA", None, "brpe"],
        ["Cada macaco no seu galho.", "ALCIDES_DE_LIMA", None, "brmg"],
        ["Em terra de cego, quem tem um olho \u00e9 rei.", "ALUISIO_SOARES_DE_SOUSA", None, "brrj"],
        ["A ocasi\u00e3o faz o ladr\u00e3o.", "FRANCISCO_JOSE_MOREIRA_MOTA", None, "brce"],
        ["De gr\u00e3o em gr\u00e3o, a galinha enche o papo.", "EVALDO_ANDRADA_CORREA", None, "brrs"],
        ["Mais vale um p\u00c1ssaro na m\u00e3o do que dois voando.", "DORIS_ALEXANDER", None, "bralemanha"],
        ["Quem n\u00e3o arrisca, n\u00e3o petisca.", "DONALDO_LUIZ_DE_ALMEIDA", None, "brgo"],
        ["A uni\u00e3o faz a for\u00e7a.", "GERONCIO_HENRIQUE_NETO", None, "bral"],
        ["Em boca fechada n\u00e3o entra mosquito.", "MALU_NATEL_FREIRE_WEBER", None, "brpr"],
        ["Quem n\u00e3o tem dinheiro, n\u00e3o tem v\u00edcios.", "INES_VIEIRA_BOGEA", None, "bres"],
        ["Quando voc\u00ea n\u00e3o corre nenhum risco, voc\u00ea arrisca tudo.", "MARIA_ASSUNCAO_SOUSA", None, "brpi"]
    ],
    # Enable the weighted sampler
    use_weighted_sampler=True,
    # Ensures that all speakers are seen in the training batch equally no matter how many samples each speaker has
    # weighted_sampler_attrs={"language": 1.0, "speaker_name": 1.0},
    weighted_sampler_attrs={"language": 1.0},
    weighted_sampler_multipliers={
        # "speaker_name": {
        # you can force the batching scheme to give a higher weight to a certain speaker and then this speaker will appears more frequently on the batch.
        # It will speedup the speaker adaptation process. Considering the CML train dataset and "new_speaker" as the speaker name of the speaker that you want to adapt.
        # The line above will make the balancer consider the "new_speaker" as 106 speakers so 1/4 of the number of speakers present on CML dataset.
        # 'new_speaker': 106, # (CML tot. train speaker)/4 = (424/4) = 106
        # }
    },
    # It defines the Speaker Consistency Loss (SCL) α to 9 like the YourTTS paper
    speaker_encoder_loss_alpha=9.0,
)

# Load all the datasets samples and split traning and evaluation sets
train_samples, eval_samples = load_tts_samples(
    config.datasets,
    eval_split=True,
    eval_split_max_size=config.eval_split_max_size,
    eval_split_size=config.eval_split_size,
)

# Init the model
model = Vits.init_from_config(config)

# Init the trainer and 🚀
trainer = Trainer(
    TrainerArgs(restore_path=RESTORE_PATH, skip_train_epoch=SKIP_TRAIN_EPOCH, start_with_eval=True),
    config,
    output_path=OUT_PATH,
    model=model,
    train_samples=train_samples,
    eval_samples=eval_samples,
)
trainer.fit()
